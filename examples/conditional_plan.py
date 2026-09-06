'''Finite logical example: a validated route is initially still conditional.'''

import prospection as p


def demonstration():
    scope = {
        'environment': p.content_id({'name': 'boolean-example-v1'}),
        'definitions': p.content_id({'logic': 'classical-propositional'}),
        'atoms': ['a', 'b'], 'assumptions': [],
    }
    state = p.initial(scope, 100)
    events = []

    def send(kind, **fields):
        nonlocal state
        event = dict(id=f'e{len(events) + 1}', kind=kind, **fields)
        state, answer = p.step(state, event)
        events.append({'event': event, 'answer': answer})
        return answer

    first = ['or', ['atom', 'a'], ['not', ['atom', 'a']]]
    second = ['implies', ['atom', 'b'], ['atom', 'b']]
    a = send('declare', formula=first)['claim']
    b = send('declare', formula=second)['claim']
    goal = send('declare', formula=['and', first, second])['claim']
    send('sketch', target=goal, premises=sorted([a, b]))
    before = p.status(state, goal)
    send('certify', claim=a)
    halfway = p.status(state, goal)
    send('certify', claim=b)
    after = p.status(state, goal)
    return {
        'profile': 'F1',
        'meaning': 'Propositional example, not a proof of an agent program.',
        'goal_status': [before, halfway, after],
        'spent': state['spent'], 'available': state['available'],
        'scope': scope, 'events': events,
        'witness_ranks': state['ranks'],
    }
