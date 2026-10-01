'''Fresh resumption through an external SQLite checkpoint and fenced owners.'''

import os
from pathlib import Path
import sqlite3

from .admission import Session
from .api import check_request, handle
from .codec import Rejected, canonical, cid, decode, fields, integer, need, ref


def _sync_directory(path):
    # Windows has no directory fsync; SQLite's Windows VFS skips it too.
    if os.name != 'posix':
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class DurableSession:
    '''One trusted database per session; candidate requests cannot pick it.'''

    @staticmethod
    def _connect(path):
        connection = sqlite3.connect(path, isolation_level=None, timeout=5)
        connection.execute('PRAGMA synchronous=FULL')
        return connection

    @classmethod
    def create(cls, path, baseline, total, key, manifest, levels=None,
               baseline_guarantees=None):
        session = Session(baseline, total, key, manifest, levels,
                          baseline_guarantees)
        blob = canonical(session.snapshot())
        digest = cid('SessionSnapshot', decode(blob))
        path = Path(path).resolve()
        # Exclusive creation prevents resetting an existing high-water mark.
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        connection = cls._connect(path)
        try:
            connection.execute(
                'CREATE TABLE checkpoint (id INTEGER PRIMARY KEY CHECK(id=1),'
                'revision INTEGER NOT NULL, digest TEXT NOT NULL, '
                'snapshot BLOB NOT NULL, pending INTEGER NOT NULL)')
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('INSERT INTO checkpoint VALUES (1,0,?,?,0)',
                               (digest, blob))
            connection.execute('COMMIT')
            _sync_directory(path.parent)
        except BaseException:
            connection.close()
            raise
        return cls._bind(session, connection, 0, digest)

    @classmethod
    def _bind(cls, session, connection, revision, digest):
        result = cls.__new__(cls)
        result._session = session
        result._connection = connection
        result._revision = revision
        result._digest = digest
        return result

    def _row(self, include_snapshot=False):
        columns = ('revision,digest,snapshot,pending' if include_snapshot
                   else 'revision,digest,NULL,pending')
        row = self._connection.execute(
            'SELECT ' + columns + ' FROM checkpoint WHERE id=1').fetchone()
        need(row is not None, 'INTEGRITY')
        integer(row[0], 0)
        ref(row[1])
        need(row[3] in (0, 1), 'INTEGRITY')
        return row

    def _current(self, pending=0, include_snapshot=False):
        row = self._row(include_snapshot)
        need(row[:2] == (self._revision, self._digest), 'STALE')
        need(row[3] == pending, 'PHASE')
        return row

    def checkpoint(self):
        row = self._current(include_snapshot=True)
        snapshot = decode(row[2])
        need(cid('SessionSnapshot', snapshot) == row[1], 'INTEGRITY')
        return snapshot, {'revision': row[0], 'digest': row[1]}

    @classmethod
    def open(cls, path, key):
        '''Recover the latest committed state when a reply was lost.'''
        path = Path(path).resolve()
        need(path.is_file(), 'REFERENCE')
        connection = cls._connect(path)
        try:
            row = connection.execute(
                'SELECT revision,digest,snapshot,pending FROM checkpoint '
                'WHERE id=1').fetchone()
            need(row is not None, 'INTEGRITY')
            need(row[3] == 0, 'PHASE')
            snapshot = decode(row[2])
            anchor = {'revision': row[0], 'digest': row[1]}
        finally:
            connection.close()
        # A concurrent advance between read and claim rejects with STALE.
        return cls.restore(path, snapshot, key, anchor)

    @classmethod
    def restore(cls, path, snapshot, key, anchor):
        fields(anchor, ('revision', 'digest'))
        integer(anchor['revision'], 0)
        ref(anchor['digest'])
        # Integrity decoding alone is never the resumption authority.
        session = Session.restore_integrity(snapshot, key, anchor['digest'])
        path = Path(path).resolve()
        need(path.is_file(), 'REFERENCE')
        connection = cls._connect(path)
        result = cls._bind(session, connection, anchor['revision'],
                           anchor['digest'])
        try:
            connection.execute('BEGIN IMMEDIATE')
            row = result._current(include_snapshot=True)
            need(row[2] == canonical(snapshot), 'INTEGRITY')
            revision = integer(row[0] + 1, 1)
            connection.execute('UPDATE checkpoint SET revision=? WHERE id=1',
                               (revision,))
            connection.execute('COMMIT')
            result._revision = revision
            return result
        except BaseException:
            if connection.in_transaction:
                connection.execute('ROLLBACK')
            connection.close()
            raise

    def handle(self, request):
        connection = self._connection
        connection.execute('BEGIN IMMEDIATE')
        try:
            row = self._current()
            try:
                check_request(self._session, request)
            except Rejected as error:
                connection.execute('ROLLBACK')
                return canonical({'code': str(error), 'value': None})
            revision = integer(row[0] + 1, 1)
            # Persist before executing. An uncertain outcome blocks restart.
            connection.execute('UPDATE checkpoint SET pending=1 WHERE id=1')
            connection.execute('COMMIT')
        except BaseException:
            if connection.in_transaction:
                connection.execute('ROLLBACK')
            raise
        response = handle(self._session, request)
        snapshot = self._session.snapshot()
        blob = canonical(snapshot)
        digest = cid('SessionSnapshot', snapshot)
        connection.execute('BEGIN IMMEDIATE')
        try:
            self._current(pending=1)
            connection.execute(
                'UPDATE checkpoint SET revision=?,digest=?,snapshot=?,'
                'pending=0 WHERE id=1', (revision, digest, blob))
            connection.execute('COMMIT')
        except BaseException:
            if connection.in_transaction:
                connection.execute('ROLLBACK')
            raise
        self._revision, self._digest = revision, digest
        # The reply becomes visible only after the new checkpoint commits.
        return response

    def close(self):
        self._connection.close()
