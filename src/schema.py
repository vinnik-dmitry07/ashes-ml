'''Closed structural schemas. Semantic validators remain profile-specific.'''

from .codec import canonical, decode, fields, integer, need, ref


SCHEMAS = {
    'GroundState': {'position': 'Nat', 'key': 'Bool', 'opened': ['Nat'],
                    'overlay': 'Bool'},
    'Observation': {'position': 'Nat', 'key': 'Bool', 'opened': ['Nat'],
                    'visible_success': 'Bool', 'level': 'Nat'},
    'ActionIntent': {'action': 'Text', 'prediction': 'Prediction',
                     'state': 'Ref'},
    'StepRecord': {'index': 'Nat', 'intent': 'ActionIntent', 'commit': 'Ref',
                   'before': 'GroundState', 'after': 'GroundState',
                   'observation': 'Observation', 'prediction_hit': 'Bool',
                   'previous': 'Ref'},
    'Trace': {'kind': 'Text', 'assignment': 'Ref', 'environment': 'Ref',
              'level': 'Nat',
              'candidate': 'Ref', 'generation': 'Nat', 'steps': ['StepRecord'],
              'final': 'GroundState', 'reward': 'Bool', 'termination': 'Text',
              'error': {'nullable': 'Text'}},
    'Assignment': {'sequence': 'Nat', 'manifest': 'Ref', 'environment': 'Ref',
                   'candidate': 'Ref', 'generation': 'Nat', 'level': 'Nat',
                   'repetition': 'Nat', 'mission': 'Ref',
                   'guarantees': {'nullable': 'Ref'}},
    'Receipt': {'binding': 'Assignment', 'trace': 'Trace'},
    'Envelope': {'receipt': 'Receipt', 'tag': 'Ref'},
    'OperationalClaim': {'ground_success': 'Bool', 'prediction_hits': 'Nat',
                         'steps': 'Nat', 'trace': 'Ref'},
    'EvaluationPlan': {'index': 'Nat', 'parent': 'Ref', 'candidate': 'Ref',
                       'generation': 'Nat', 'manifest': 'Ref',
                       'environment': 'Ref', 'levels': ['Nat'],
                       'assignments': [['Ref']], 'mode': 'Text',
                       'mission': 'Ref', 'parent_guarantees': 'Guarantees',
                       'candidate_guarantees': 'Guarantees'},
    'ReleaseDecision': {'kind': 'Text', 'plan': 'Ref', 'generation': 'Nat',
                        'pairs': [['Bool']], 'accept': 'Bool',
                        'scope': ['Nat'],
                        'receipts': ['Ref'], 'mission': 'Ref',
                        'guarantees': 'Ref',
                        'assessments': ['AssessmentEnvelope'],
                        'improvement': 'Improvement'},
    'ExecutionCost': {'actions': 'Nat', 'vm_fuel': 'Nat',
                      'program_bytes': 'Nat'},
    'Improvement': {'profile': 'Text', 'success_gain': 'Bool',
                    'cost_comparable': 'Bool', 'cost_nonworse': 'Bool',
                    'cost_strict': 'Bool', 'cost_pairs': [['ExecutionCost']]},
    'TrainingAdmission': {'kind': 'Text', 'profile': 'Text',
                          'environment': 'Ref',
                          'manifest': 'Ref', 'assignment': 'Ref',
                          'trace': 'Ref',
                          'mechanism': 'Text', 'scope': {'level': 'Nat'},
                          'prediction_hits': 'Nat', 'mission': 'Ref',
                          'guarantees': 'Ref',
                          'assessment': 'AssessmentEnvelope'},
    'LocalPolicy': {'kind': 'Text', 'environment': 'Ref', 'sources': ['Ref'],
                    'table': {'map': 'Text'}},
    'Job': {'upper': 'Nat', 'charge': 'Nat', 'phase': 'Text', 'fence': 'Bool',
            'receipt': {'nullable': 'Ref'}},
    'State': {'total': 'Nat', 'free': 'Nat', 'spent': 'Nat',
              'jobs': {'map': 'Job'}, 'active': 'Ref', 'generation': 'Nat',
              'open_runs': 'Nat', 'sequence': 'Nat'},
    'Genesis': 'State',
    'LogRecord': {'principal': 'Text', 'event': 'Event', 'before': 'Ref',
                  'after': 'Ref', 'previous': 'Ref'},
    'ProofLibrary': {'map': {'goal': 'Formula', 'term': 'Term'}},
    'ProofCertificate': {'kind': 'Text', 'profile': 'Text',
                         'environment': 'Ref',
                         'goal': 'Formula', 'term': 'Term', 'visits': 'Nat'},
    'TraceStart': {'assignment': 'Ref', 'environment': 'Ref'},
    'PolicyObservation': {'environment': 'Ref', 'level': 'Nat',
                          'position': 'Nat', 'key': 'Bool', 'opened': ['Nat']},
    'KnowledgeEntry': {'text': 'Text', 'tokens': ['Text'],
                       'features': ['Text'],
                       'predicate': 'Text', 'arguments': ['Text'],
                       'polarity': 'Bool', 'status': 'Text', 'scope': 'Ref',
                       'evidence': ['Ref']},
    'KnowledgeAssertion': {'scope': 'Ref', 'predicate': 'Text',
                           'arguments': ['Text'], 'polarity': 'Bool'},
    'SyntheticTrace': {'kind': 'Text', 'model': 'Ref', 'actions': ['Text']},
    'ExecutionScope': {'manifest': 'Ref', 'environment': 'Ref'},
    'Guarantees': {'require_ground_goal': 'Bool', 'max_actions': 'Nat',
                   'max_program_bytes': 'Nat'},
    'Mission': {'kind': 'Text', 'environment': 'Ref', 'manifest': 'Ref',
                'levels': ['Nat'], 'absolute_success': 'Text',
                'improvement_profile': 'Text',
                'floor': 'Guarantees', 'observer': 'Ref', 'evaluator': 'Ref'},
    'Assessment': {'kind': 'Text', 'principal': 'Ref', 'assignment': 'Ref',
                   'source': 'Ref', 'mission': 'Ref', 'guarantees': 'Ref',
                   'outcome': 'OperationalClaim', 'cost': 'ExecutionCost',
                   'violations': ['Text']},
    'AssessmentEnvelope': {'assessment': 'Assessment', 'tag': 'Ref'},
    'RequestLogStart': {'mission': 'Ref'},
    'RequestRecord': {'index': 'Nat', 'request_hex': 'Text', 'before': 'Ref',
                      'after': 'Ref', 'result': 'Ref', 'code': 'Text',
                      'previous': 'Ref'},
    'WireResult': {'code': 'Text', 'value': 'CanonicalValue'},
    'CheckpointAnchor': {'revision': 'Nat', 'digest': 'Ref'},
    'Environment': {'profile': 'Text', 'version': 'Nat', 'actions': ['Text'],
                    'level_min': 'Nat', 'level_max': 'Nat', 'goal': 'Text',
                    'effects': 'Text'},
    'SessionSnapshot': {
        'version': 'Text', 'levels': ['Nat'],
        'programs': {'map': 'ProgramText'},
        'plans': {'map': 'EvaluationPlan'}, 'used': ['Ref'],
        'training_used': ['Ref'], 'active_plan': {'nullable': 'Ref'},
        'requests_used': 'Nat',
        'mission': 'Mission', 'mission_id': 'Ref',
        'published_contracts': {'map': 'Guarantees'},
        'contracts': {'map': 'Guarantees'}, 'decisions': ['ReleaseDecision'],
        'request_log': ['RequestRecord'], 'request_log_bytes': 'Nat',
        'request_log_head': 'Ref',
        'dataset': {'map': {'certificate': 'TrainingAdmission',
                            'trace': 'Trace'}},
        'ledger': {'genesis': 'State', 'state': 'State', 'log': ['LogRecord'],
                   'head': 'Ref'},
        'runner': {'manifest': 'Ref', 'sequence': 'Nat',
                   'issued': {'map': 'Assignment'},
                   'receipts': {'map': 'Envelope'}, 'fenced': ['Ref']},
    },
}
HASH_KINDS = tuple(sorted(SCHEMAS)) + ('Program', 'Manifest')


def validate_schema(value, schema):
    canonical(value)

    def visit(item, tag):
        if type(tag) is str:
            if tag in SCHEMAS:
                return visit(item, SCHEMAS[tag])
            if tag == 'Nat':
                return integer(item, 0)
            if tag == 'Ref':
                return ref(item)
            if tag == 'Text':
                return need(type(item) is str)
            if tag == 'Bool':
                return need(type(item) is bool)
            if tag == 'CanonicalValue':
                canonical(item)
                return True
            if tag == 'Program':
                from .language import check
                return check(item)
            if tag == 'ProgramText':
                from .environment import check_agent
                need(type(item) is str)
                return check_agent(decode(item.encode('ascii')))
            if tag == 'Formula':
                from .proofs import formula
                return formula(item)
            if tag == 'Prediction':
                from .environment import prediction
                return prediction(item, 12)
            if tag == 'Manifest':
                return visit(item, {'map': 'Ref'})
            if tag == 'Event':
                from .kernel import ROLES
                need(type(item) is dict and item.get('op') in ROLES)
                op = item['op']
                members = {
                    'reserve': ('op', 'job', 'upper'),
                    'start_run': ('op',), 'close_run': ('op',),
                    'publish': ('op', 'candidate', 'generation'),
                    'rollback': ('op', 'candidate', 'generation'),
                    'complete': ('op', 'job', 'actual', 'receipt'),
                }.get(op, ('op', 'job'))
                return fields(item, members)
            if tag == 'Term':
                need(type(item) is list and item and type(item[0]) is str)
                op = item[0]
                arity = {'var': 2, 'unit': 1, 'ref': 2, 'lam': 3, 'app': 3,
                         'pair': 3, 'fst': 2, 'snd': 2, 'inl': 3, 'inr': 3,
                         'case': 4, 'absurd': 3}
                need(op in arity and len(item) == arity[op])
                if op == 'var':
                    integer(item[1], 0)
                elif op == 'ref':
                    from .codec import name
                    name(item[1])
                else:
                    for index, child in enumerate(item[1:], 1):
                        formula_position = ((op in ('lam', 'absurd', 'inr')
                                             and index == 1)
                                            or (op == 'inl' and index == 2))
                        visit(child, 'Formula' if formula_position else 'Term')
                return True
            need(False)
        if type(tag) is list:
            need(type(item) is list)
            for child in item:
                visit(child, tag[0])
        elif set(tag) == {'map'}:
            need(type(item) is dict)
            for child in item.values():
                visit(child, tag['map'])
        elif set(tag) == {'nullable'}:
            if item is not None:
                visit(item, tag['nullable'])
        else:
            fields(item, tag)
            for key, child_type in tag.items():
                visit(item[key], child_type)

    visit(value, schema)
    return True
