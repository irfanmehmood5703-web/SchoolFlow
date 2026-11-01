"""Evidence-based institute onboarding checklist and reviewed completion marker."""
import copy,hashlib,json
from datetime import date,datetime
from zoneinfo import ZoneInfo
from flask import g,request,session
from itsdangerous import BadData,URLSafeTimedSerializer


def configure_setup_readiness(app,db,Student):
    models=app.extensions['institute_setup_models'];Profile=models['profile'];Campus=models['campus'];Map=models['mapping'];Settings=app.extensions['record_models']['settings'];fee=app.extensions['fee_setup_models'];Item=app.extensions['school_settings_models']['item'];Audit=app.extensions['ops_models']['audit']
    def snapshot():
        profile=db.session.get(Profile,1);data=profile.data if profile else {};campuses=Campus.query.order_by(Campus.name).all();maps=Map.query.order_by(Map.campus,Map.class_name).all();options=Settings.query.order_by(Settings.id).all();heads=fee['head'].query.order_by(fee['head'].key).all();plans=fee['schedule'].query.order_by(fee['schedule'].id).all();items=Item.query.order_by(Item.id).all()
        catalog={}
        for r in options:catalog.setdefault(r.category,set()).add(r.value)
        active=[c for c in campuses if c.active];links=[m for m in maps if m.active and m.campus in {c.name for c in active}];checks=[]
        def add(key,label,ready,message,required=True):checks.append(dict(key=key,label=label,ready=bool(ready),message=message,required=required))
        add('school','School & campuses',data.get('name') and active,'Institute name and at least one active campus are required.')
        add('catalog','Classes, sections & groups',all(catalog.get(k) for k in ('class_name','section','group_name')),'Add the classes, sections and groups offered by this institute.')
        linked=bool(active) and all(any(m.campus==c.name for m in links) for c in active)
        linked=linked and all(m.class_name in catalog.get('class_name',set()) and all(m.data.get(k) and set(m.data[k])<=catalog.get(cat,set()) for k,cat in [('sections','section'),('groups','group_name'),('fee_plans','fee_plan')]) and m.data.get('academic_session') in catalog.get('academic_session',set()) for m in links)
        add('maps','Campus class map',linked,'Every active campus needs valid class, section, group, session and fee-plan links.')
        try:academic=data.get('current_session') in catalog.get('academic_session',set()) and date.fromisoformat(data.get('year_start',''))<=date.fromisoformat(data.get('year_end',''))
        except (ValueError,TypeError):academic=False
        add('academic','Sessions & academic year',academic,'Choose a current session and academic year dates.')
        add('heads','Fee heads',bool(heads),'Configure fee heads and their charging timings.')
        covered=bool(links) and all(any(p.campus==m.campus and p.class_name==m.class_name and p.name==name for p in plans) for m in links for name in m.data.get('fee_plans',[]))
        add('plans','Mapped fee schedules',covered,'Each mapped fee plan needs a saved schedule for that campus and class; copied names alone are insufficient.')
        fine_heads={h.key for h in heads if h.timing=='fine'}
        late=[r for r in items if r.kind=='late-fee-policy'];valid_late=all(r.data.get('mode')=='none' or r.data.get('head') in fine_heads for r in late)
        add('late','Late-fee policy',valid_late,'Optional: disabled until a policy is configured. Enabled policies require a valid fine head.',False)
        attendance=[r for r in items if r.kind=='attendance-fine-policy'];valid_att=all(not any(x.get('enabled') for x in r.data.get('rules',{}).values()) or r.data.get('head') in fine_heads for r in attendance)
        add('attendance','Attendance-fine policy',valid_att,'Optional: disabled until configured. Sandwich Leave stays disabled.',False)
        branding=[r for r in items if r.kind=='challan-branding'];valid_branding=True
        try:
            for r in branding:
                if r.data.get('show_payment_qr'):
                    if not r.data.get('payment_url'):valid_branding=False
                    else:app.extensions['challan_consumer_helpers']['validate_url'](r.data['payment_url'])
        except ValueError:valid_branding=False
        add('branding','Challan branding',valid_branding,'Default branding is available. An enabled payment-link QR needs a valid supplied HTTPS link.',False)
        add('mode','Light / Full mode',data.get('ui_mode','light') in ('light','full'),'Choose the default for optional advanced panels.',False)
        sources=dict(profile=[profile.version,data] if profile else None,campuses=[[c.name,c.version,c.active,c.city,c.short_name] for c in campuses],maps=[[m.campus,m.class_name,m.version,m.active,m.data] for m in maps],catalog=[[r.id,r.category,r.class_name,r.value] for r in options],heads=[[h.key,h.version,h.timing,h.months,h.label] for h in heads],plans=[[p.id,p.version,p.name,p.campus,p.class_name,p.lines] for p in plans],items=[[r.id,r.kind,r.version,r.data] for r in items])
        stamp=hashlib.sha256(json.dumps(sources,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        return dict(checks=checks,ready=all(c['ready'] for c in checks),ready_count=sum(c['ready'] for c in checks),total=len(checks),stamp=stamp,activated_at=data.get('setup_activated_at',''),profile_version=profile.version if profile else 0)
    def actor():return dict(scope=(getattr(g,'school_identity',None) or {}).get('scope'),owner=session.get('owner_id'),csrf=session.get('record_csrf'))
    def signer():return URLSafeTimedSerializer(app.config['SECRET_KEY'],salt='schoolflow-complete-setup-v1')
    def token(snap):return signer().dumps(dict(actor=actor(),stamp=snap['stamp'],version=snap['profile_version']))
    def complete(raw,version):
        if len(raw)>131072:raise ValueError('Invalid setup review.')
        try:payload=signer().loads(raw,max_age=900)
        except BadData:raise ValueError('Reload the current setup checklist before completing setup.')
        snap=snapshot()
        if payload!=dict(actor=actor(),stamp=snap['stamp'],version=snap['profile_version']) or str(snap['profile_version'])!=version:raise ValueError('School settings changed. Review the current checklist again.')
        if not snap['ready']:raise ValueError('Complete the items marked Needs attention before finishing institute setup.')
        row=db.session.get(Profile,1);before=copy.deepcopy(row.data);data=dict(row.data)
        data.update(setup_activated_at=datetime.now(ZoneInfo('Asia/Karachi')).isoformat(),setup_activated_by=session.get('owner_id') or 'demo')
        row.data=data;db.session.add(Audit(action='Complete institute setup',data=dict(owner_id=session.get('owner_id'),review_stamp=snap['stamp'],before=before,completed_at=data['setup_activated_at'])));db.session.commit()
    app.extensions['setup_readiness_helpers']=dict(snapshot=snapshot,token=token,complete=complete)
