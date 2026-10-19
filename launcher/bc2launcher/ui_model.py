def controls(state, selected, busy):
    return dict(check=bool(selected and not busy),
                update=bool(selected and not busy and state in ('UPDATE_REQUIRED','ERROR')),
                play=bool(selected and not busy and state=='READY'),
                rollback=bool(selected and not busy),choose=not busy,cancel=busy)
