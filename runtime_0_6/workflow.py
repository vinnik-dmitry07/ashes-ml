'''A typed register machine over the unchanged AHSL-Core 0.5.

One advance executes at most one instruction. Await does not spend fuel
while the provider has not supplied an outcome.
'''

from copy import deepcopy

from contracts import evaluate
from kernel import core


def expr_type(expr, registers):
    core.require(type(expr) is dict and len(expr) == 1)
    if 'literal' in expr:
        core.typed_value(expr['literal'])
        return expr['literal']['type']
    core.fields(expr, ('register',))
    name = expr['register']
    core.require(type(name) is str and name in registers)
    return registers[name]['type']


def resolve(expr, registers):
    if 'literal' in expr:
        return deepcopy(expr['literal'])
    return deepcopy(registers[expr['register']])


def validate(program, manifest):
    core.fields(program, (
        'registers', 'inputs', 'handles', 'entry', 'nodes', 'output', 'fuel',
    ))
    core.named_values(program['registers'])
    core.require(len(program['registers']) <= 256)
    core.require(type(program['inputs']) is list)
    core.names(program['inputs'])
    core.require(set(program['inputs']) <= set(program['registers']))
    core.require(type(program['handles']) is dict)
    core.require(len(program['handles']) <= 256)
    for name, component in program['handles'].items():
        core.identifier(name)
        core.require(
            type(component) is str and component in manifest['components']
        )
    nodes = program['nodes']
    core.require(type(nodes) is dict and 0 < len(nodes) <= 4096)
    for node in nodes:
        core.identifier(node)
    core.require(type(program['entry']) is str and program['entry'] in nodes)
    core.type_name(program['output'])
    core.nat(program['fuel'])
    core.require(program['fuel'] <= 100000)
    registers = program['registers']

    def register(name, expected=None):
        core.require(type(name) is str and name in registers)
        if expected is not None:
            core.require(registers[name]['type'] == expected)

    for instruction in nodes.values():
        core.require(type(instruction) is dict)
        op = instruction.get('op')
        successors = []
        if op == 'set':
            core.fields(instruction, ('op', 'register', 'value', 'next'))
            register(instruction['register'])
            core.require(
                expr_type(instruction['value'], registers)
                == registers[instruction['register']]['type']
            )
            successors = ['next']
        elif op == 'jump':
            core.fields(instruction, ('op', 'next'))
            successors = ['next']
        elif op == 'branch':
            core.fields(instruction, ('op', 'test', 'then', 'else'))
            core.require(expr_type(instruction['test'], registers) == 'bool')
            successors = ['then', 'else']
        elif op in ('spawn', 'await'):
            handle = instruction.get('handle')
            core.require(type(handle) is str and handle in program['handles'])
            component = manifest['components'][program['handles'][handle]]
            register(instruction.get('error_register'), 'text')
            if op == 'spawn':
                core.fields(instruction, (
                    'op', 'handle', 'args', 'ok', 'error', 'error_register',
                ))
                args = instruction['args']
                core.require(type(args) is dict)
                core.require(set(args) == set(component['inputs']))
                for name, expr in args.items():
                    core.require(
                        expr_type(expr, registers) == component['inputs'][name]
                    )
                successors = ['ok', 'error']
            else:
                core.fields(instruction, (
                    'op', 'handle', 'output_register', 'error_register',
                    'ok', 'error', 'unknown',
                ))
                register(instruction['output_register'], component['output'])
                successors = ['ok', 'error', 'unknown']
        elif op == 'halt':
            core.fields(instruction, ('op', 'value'))
            core.require(
                expr_type(instruction['value'], registers) == program['output']
            )
        else:
            raise core.SchemaError('BAD_SCHEMA')
        for successor in successors:
            target = instruction[successor]
            core.require(type(target) is str and target in nodes)


def initial(program, args):
    core.named_values(args)
    core.require(set(args) == set(program['inputs']))
    for name, value in args.items():
        core.require(value['type'] == program['registers'][name]['type'])
    registers = deepcopy(program['registers'])
    registers.update(deepcopy(args))
    return {
        'pc': program['entry'], 'registers': registers,
        'handles': dict.fromkeys(program['handles']),
        'fuel': program['fuel'], 'serial': 0, 'calls': 0,
        'status': 'ready', 'result': None, 'failure': None,
    }


def advance(program, vm, kernel, skills):
    if vm['status'] in ('halted', 'exhausted', 'failed'):
        return vm, kernel, [], 'TERMINAL'
    vm = deepcopy(vm)
    if vm['fuel'] == 0:
        vm['status'] = 'exhausted'
        return vm, kernel, [], 'FUEL_EXHAUSTED'
    instruction = program['nodes'][vm['pc']]
    op = instruction['op']
    if op == 'await':
        job_id = vm['handles'][instruction['handle']]
        if job_id is not None:
            phase = kernel['jobs'][job_id]['status']
            if phase in ('reserved', 'running'):
                vm['status'] = 'blocked'
                return vm, kernel, [], 'WAITING'
    vm['status'] = 'ready'
    vm['fuel'] -= 1
    requests = []

    def emit(kind, **payload):
        nonlocal kernel
        vm['serial'] += 1
        event = {'id': 'w' + str(vm['serial']), 'kind': kind, **payload}
        kernel, result, outgoing = core.step(kernel, 'agent', event)
        requests.extend(outgoing)
        return result

    def error(code, branch='error'):
        vm['registers'][instruction['error_register']] = {
            'type': 'text', 'value': code,
        }
        vm['pc'] = instruction[branch]

    if op == 'set':
        vm['registers'][instruction['register']] = resolve(
            instruction['value'], vm['registers'],
        )
        vm['pc'] = instruction['next']
    elif op == 'jump':
        vm['pc'] = instruction['next']
    elif op == 'branch':
        test = resolve(instruction['test'], vm['registers'])['value']
        vm['pc'] = instruction['then'] if test else instruction['else']
    elif op == 'halt':
        vm['result'] = resolve(instruction['value'], vm['registers'])
        vm['status'] = 'halted'
    elif op == 'spawn':
        handle = instruction['handle']
        previous = vm['handles'][handle]
        if previous is not None and kernel['jobs'][previous]['status'] in (
            'reserved', 'running', 'unknown',
        ):
            error('HANDLE_BUSY')
        else:
            component = program['handles'][handle]
            args = {
                key: resolve(value, vm['registers'])
                for key, value in instruction['args'].items()
            }
            vm['calls'] += 1
            job_id = 'J' + str(vm['calls'])
            result = emit(
                'reserve', job=job_id, component=component, args=args,
            )
            if result['code'] != 'OK':
                error(result['code'])
            else:
                vm['handles'][handle] = job_id
                snapshot = kernel['jobs'][job_id]['snapshot']
                if not evaluate(skills[component]['pre'], args, snapshot):
                    emit('cancel', job=job_id)
                    error('PRECONDITION')
                else:
                    result = emit('dispatch', job=job_id)
                    if result['code'] == 'OK':
                        vm['pc'] = instruction['ok']
                    else:
                        emit('cancel', job=job_id)
                        error(result['code'])
    elif op == 'await':
        job_id = vm['handles'][instruction['handle']]
        if job_id is None:
            error('NO_HANDLE')
        else:
            job = kernel['jobs'][job_id]
            if job['status'] == 'unknown':
                error('UNKNOWN', 'unknown')
            elif job['result']['code'] == 'SUCCESS':
                vm['registers'][instruction['output_register']] = deepcopy(
                    job['result']['value'],
                )
                vm['pc'] = instruction['ok']
            else:
                error(job['result']['code'])
    return vm, kernel, requests, 'ADVANCED'
