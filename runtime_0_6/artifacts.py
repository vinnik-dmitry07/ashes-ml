'''Immutable, content-addressed records; payload execution is external.'''

from copy import deepcopy
import hashlib
import json

import contracts
from kernel import core
import workflow


KINDS = frozenset((
    'skill', 'code', 'prompt', 'weights', 'latent', 'memory', 'data',
    'plan', 'updater', 'evaluator', 'trace', 'summary',
))


def canonical(value):
    def check(item, depth=0):
        core.require(depth <= 64)
        if item is None or type(item) is bool:
            return
        if type(item) is int:
            core.nat(item)
        elif type(item) is str:
            core.scalar_text(item)
        elif type(item) is list:
            for child in item:
                check(child, depth + 1)
        elif type(item) is dict:
            for key, child in item.items():
                core.scalar_text(key)
                check(child, depth + 1)
        else:
            raise core.SchemaError('BAD_SCHEMA')
    check(value)
    return json.dumps(
        value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
        allow_nan=False,
    ).encode('utf-8')


def content_id(value):
    return 'h' + hashlib.sha256(canonical(value)).hexdigest()


def validate(artifact):
    core.fields(artifact, ('kind', 'format', 'payload', 'dependencies'))
    core.require(type(artifact['kind']) is str and artifact['kind'] in KINDS)
    core.identifier(artifact['format'])
    core.names(artifact['dependencies'])
    canonical(artifact)
    if artifact['kind'] == 'skill':
        core.fields(artifact['payload'], ('implementation', 'pre', 'post'))
        core.identifier(artifact['payload']['implementation'])
        core.require(
            artifact['payload']['implementation'] in artifact['dependencies']
        )


def add(registry, artifact):
    validate(artifact)
    core.require(set(artifact['dependencies']) <= set(registry))
    reference = content_id(artifact)
    if reference in registry:
        core.require(registry[reference] == artifact)
    registry[reference] = deepcopy(artifact)
    return reference


def manifest_for(policy, configuration):
    manifest = deepcopy(policy['manifest'])
    for name, value in configuration['initial'].items():
        manifest['cells'][name]['value'] = deepcopy(value)
    return manifest


def configuration_id(policy, configuration):
    return content_id({'policy': content_id(policy), 'configuration': configuration})


def validate_configuration(policy, registry, configuration):
    core.fields(configuration, ('program', 'bindings', 'initial'))
    manifest = policy['manifest']
    core.named_values(configuration['initial'])
    core.require(set(configuration['initial']) == set(manifest['cells']))
    for name, value in configuration['initial'].items():
        core.require(value['type'] == manifest['cells'][name]['type'])
        if name not in policy['initializable']:
            core.require(value == manifest['cells'][name]['value'])
    core.require(type(configuration['bindings']) is dict)
    core.require(set(configuration['bindings']) == set(manifest['components']))
    for name, reference in configuration['bindings'].items():
        core.identifier(reference)
        core.require(reference in registry)
        artifact = registry[reference]
        core.require(artifact['kind'] == 'skill')
        payload = artifact['payload']
        core.require(registry[payload['implementation']]['kind'] != 'skill')
        for phase in ('pre', 'post'):
            contracts.validate_predicate(
                payload[phase], manifest['components'][name],
                manifest['cells'], phase,
            )
    workflow.validate(configuration['program'], manifest)
    program = configuration['program']
    interface = policy['interface']
    core.require(set(program['inputs']) == set(interface['inputs']))
    core.require(program['output'] == interface['output'])
    for name, tag in interface['inputs'].items():
        core.require(program['registers'][name]['type'] == tag)
    canonical(configuration)


def skills_for(registry, configuration, policy):
    skills = {
        name: registry[reference]['payload']
        for name, reference in configuration['bindings'].items()
    }
    return {
        name: dict(payload, **{
            phase: {'op': 'and', 'values': [
                policy['contracts'][name][phase], payload[phase],
            ]} for phase in ('pre', 'post')
        }) for name, payload in skills.items()
    }
