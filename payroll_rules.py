"""Explicit SchoolFlow attendance-deduction policies, in integer paisa.

Grouping and caps are chosen on the salary plan; no unknown vendor convention
is inferred from an old nonzero Jump/Max field.
"""
from decimal import Decimal,ROUND_HALF_UP

JUMP_MODES={'per_event':'Every extra day','complete_groups':'Each complete group','started_groups':'Each started group'}
CAP_MODES={'none':'No cap','events':'Maximum deduction events','amount':'Maximum amount (PKR)'}


def parse_rule(form,i,status,money):
    def text(key,default=''):return form.get(key+'_'+str(i),default).strip()
    free=text('allowed','0');jump=text('jump','0');maximum=text('limit','0');mode=text('jump_mode');cap=text('cap_mode')
    if not free.isdigit() or not jump.isdigit() or int(free)>3660 or int(jump)>3660:raise ValueError('Allowed days and group size must be whole numbers from 0 to 3,660.')
    if not mode:
        if int(jump):raise ValueError('Choose how Jump/group size is counted before saving this legacy rule.')
        mode='per_event'
    if not cap:
        if maximum not in ('','0'):raise ValueError('Choose whether the maximum caps events or PKR before saving this legacy rule.')
        cap='none'
    if mode not in JUMP_MODES or cap not in CAP_MODES:raise ValueError('Choose a supported grouping and maximum rule.')
    if (mode=='per_event' and int(jump)!=0) or (mode!='per_event' and int(jump)<1):raise ValueError('Use group size 0 for Every extra day, or a positive size for complete/started groups.')
    limit=0;max_amount=0
    if cap=='events':
        if not maximum.isdigit() or int(maximum)>3660:raise ValueError('Maximum events must be a whole number from 0 to 3,660.')
        limit=int(maximum)
    elif cap=='amount':max_amount=money(maximum or '0')
    elif money(maximum or '0')!=0:raise ValueError('Use maximum 0 with No cap, or choose an events/PKR cap.')
    typ=text('type','Abs');frequency=text('frequency','Recursive');rate=money(text('deduction','0'))
    if typ not in ('Abs','Percent') or frequency not in ('Recursive','Once'):raise ValueError('Choose a valid deduction type and frequency.')
    if typ=='Percent' and rate>10000:raise ValueError('Percentage cannot exceed 100.')
    return dict(status=status,allowed=int(free),type=typ,amount=rate,frequency=frequency,jump=int(jump),limit=limit,jump_mode=mode,cap_mode=cap,max_amount=max_amount)


def deduction(rule,count,monthly_basic,working_days):
    jump=rule.get('jump',0);limit=rule.get('limit',0);mode=rule.get('jump_mode');cap=rule.get('cap_mode')
    if mode is None:
        if jump:raise ValueError('Review this legacy nonzero Jump rule, select a grouping mode and approve its salary plan.')
        mode='per_event'
    if cap is None:
        if limit:raise ValueError('Review this legacy maximum, select an events or PKR cap and approve its salary plan.')
        cap='none'
    if mode not in JUMP_MODES or cap not in CAP_MODES:raise ValueError('Unsupported salary deduction rule.')
    extra=max(0,count-rule.get('allowed',0))
    if mode=='per_event':events=extra
    elif jump<1:raise ValueError('A grouped deduction needs a positive group size.')
    elif mode=='complete_groups':events=extra//jump
    else:events=(extra+jump-1)//jump
    if rule.get('frequency','Recursive')=='Once':events=min(events,1)
    if cap=='events':events=min(events,limit)
    if rule.get('type','Abs')=='Percent' and events:
        if not working_days:raise ValueError('Choose the working-day count before previewing a percentage deduction.')
        amount=int((Decimal(monthly_basic)*rule['amount']*events/10000/working_days).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
    else:amount=rule.get('amount',0)*events
    before_cap=amount
    if cap=='amount':amount=min(amount,rule.get('max_amount',0))
    if amount>99999999900:raise ValueError('Calculated salary deduction exceeds the supported amount.')
    return dict(status=rule['status'],count=count,allowed=rule.get('allowed',0),extra=extra,events=events,jump_mode=mode,group_size=jump,cap_mode=cap,before_cap=before_cap,amount=amount)
