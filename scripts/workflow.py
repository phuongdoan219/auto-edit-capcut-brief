"""Machine-local inventory -> human picker -> confirmed native edit-plan compilation."""
import argparse,json,os,subprocess,sys,time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request,urlopen
import library_scan
import selection_session as S
import selection_plan
import capcut_native
import library_setup
from selection_request import effect_sticker_request


def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save(path,data):
    from picker_server import atomic_json
    atomic_json(Path(path),data)


def default_state():
    return library_setup.default_state()


def restore_confirmed_draft(work,session_path):
    """Reuse only proven user choices in a new pending revision; never confirm it."""
    work=Path(work);state=read(work/'workflow.json');session=read(session_path)
    if Path(state['session']).exists() and read(state['session']).get('status')=='confirmed':
        raise ValueError('Create a new pending work folder to revise confirmed choices')
    errors=S.validate_confirmed_session(read(state['request']),read(state['library']),session,
        S.file_hash(state['request']),S.file_hash(state['library']))
    if errors:raise ValueError('Cannot reuse choices from another request/library: '+'; '.join(errors))
    save(work/'draft-from-confirmed.json',session)


def restore_mapped_draft(work,source_work,slot_map,focus_slot=None):
    """Preserve proven user choices across an explicitly reviewed slot split.

    Missing new groups remain unselected. A combined text choice may map to one
    group only; it is never duplicated into its newly separated supporting copy.
    """
    work=Path(work);source_work=Path(source_work)
    target=read(work/'workflow.json');source=read(source_work/'workflow.json')
    request=read(target['request']);library=read(target['library'])
    if Path(target['session']).exists() and read(target['session']).get('status')=='confirmed':
        raise ValueError('Create a new pending revision before mapping choices')
    session=read(source['session'])
    errors=S.validate_confirmed_session(read(source['request']),read(source['library']),session,
        S.file_hash(source['request']),S.file_hash(source['library']))
    if errors:raise ValueError('Source choices must be confirmed and current: '+'; '.join(errors))
    if S.file_hash(source['library'])!=S.file_hash(target['library']):
        raise ValueError('Mapped drafts require the same library snapshot')
    old={s['id']:s for f in read(source['request'])['frames'] for s in f['slots']}
    new={s['id']:s for f in request['frames'] for s in f['slots']}
    if not isinstance(slot_map,dict) or any(k not in old or v not in new for k,v in slot_map.items()):
        raise ValueError('Invalid explicit slot mapping')
    if focus_slot is not None and focus_slot not in new:raise ValueError('Unknown focus slot')
    choices={}
    for sid,choice in session['choices'].items():
        dest=slot_map.get(sid,sid)
        if dest not in new:continue
        if old[sid]['role']!=new[dest]['role'] or old[sid]['categories']!=new[dest]['categories']:
            raise ValueError('Slot mapping changes asset category')
        if dest in choices:raise ValueError('Several choices map to the same group')
        choices[dest]=choice
    errors=S.validate_draft_choices(request,library,choices)
    if errors:raise ValueError('; '.join(errors))
    draft={'request_hash':S.file_hash(target['request']),'library_hash':S.file_hash(target['library']),
        'choices':choices,'source_session_hash':S.file_hash(source['session']),'slot_map':slot_map,'focus_slot':focus_slot}
    save(work/'initial-draft.json',draft)
    return {'restored_choices':len(choices),'unselected_slots':[sid for sid in new if sid not in choices]}


def prepare(request_path,work,state_dir=None,roots=None,plan=None,base=None,roughcut=None,reuse_selection=None):
    work=Path(work).resolve();work.mkdir(parents=True,exist_ok=True)
    if (work/'selection.json').exists():raise ValueError('This work folder already has a selection session; resume it or use a new folder')
    request=effect_sticker_request(read(request_path))
    if request.get('semantic_review_required') is not False:raise ValueError('AI must review frame slots and set semantic_review_required=false before opening picker')
    catalog,installed_path,setup=library_setup.load_or_setup(state_dir or default_state(),roots)
    if not catalog['summary']['projects_scanned']:raise ValueError('No readable CapCut projects found; specify the actual draft root')
    S.make_session(request,catalog)
    rp=work/'request.json';lp=work/'library.json'
    # Pin the exact inventory snapshot for this user selection. Refreshing the
    # machine-wide inventory later cannot silently change an open picker.
    save(rp,request);save(lp,catalog)
    if plan:
        pending=selection_plan.with_optional_sticker_placements(read(plan),request)
        plan=work/'plan.pending.json';save(plan,pending)
    state={'schema':'capcut-choice-workflow/1','status':'ready','request':str(rp),'library':str(lp),
           'session':str(work/'selection.json'),'service':str(work/'picker-service.json'),
           'machine_id':catalog['machine_id'],'summary':catalog['summary'],
           'preview_jobs':setup['preview_jobs'],'previews_pending':setup['previews_pending'],
           'library_mode':setup['mode'],'installed_library':str(installed_path),
           'plan':str(Path(plan).resolve()) if plan else None,'base':str(Path(base).resolve()) if base else None}
    save(work/'workflow.json',state)
    if roughcut:
        import scene_preview
        scene_preview.prepare(work,roughcut)
        state=read(work/'workflow.json')
    if reuse_selection:restore_confirmed_draft(work,reuse_selection)
    return state


def launch(work,no_open=False):
    work=Path(work).resolve();state=read(work/'workflow.json');info_path=Path(state['service'])
    if read(state['request']).get('selection_mode')=='effects_stickers':
        import scene_preview
        if not scene_preview.load(work,S.file_hash(state['request'])):
            raise ValueError('Finish Step 1 first, then run scene_preview.py --work <work> --video <roughcut.mp4> before opening choices')
    if info_path.exists():
        info=read(info_path)
        try:
            parsed=urlsplit(info['origin'])
            if parsed.hostname!='127.0.0.1' or parsed.scheme!='http':raise ValueError('Invalid picker origin')
            req=Request(info['origin']+'/api/state',headers={'Authorization':'Bearer '+info['token']})
            with urlopen(req,timeout=2) as response:result=json.load(response)
            if result['request_hash']!=S.file_hash(state['request']) or result['library_hash']!=S.file_hash(state['library']):raise ValueError('A different picker is using this work folder')
            if not no_open:
                from picker_server import open_popup
                open_popup(info['url'])
            return info
        except (OSError,ValueError,KeyError):pass
    script=Path(__file__).with_name('picker_server.py')
    args=[sys.executable,str(script),'serve','--request',state['request'],'--library',state['library'],
          '--session',state['session'],'--state',state['service'],'--port','0']
    if no_open:args.append('--no-open')
    flags=getattr(subprocess,'CREATE_NO_WINDOW',0) if os.name=='nt' else 0
    before=info_path.stat().st_mtime_ns if info_path.exists() else None
    with (work/'picker.log').open('ab') as log:
        child=subprocess.Popen(args,stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        if child.poll() is not None:raise ValueError('Picker exited; inspect '+str(work/'picker.log'))
        if info_path.exists() and info_path.stat().st_mtime_ns!=before:
            info=read(info_path);state['status']='pending_selection';save(work/'workflow.json',state);return info
        time.sleep(.1)
    raise ValueError('Picker did not become ready; inspect its log')


def resume(work,install=False,confirmed_closed=False):
    work=Path(work).resolve();state=read(work/'workflow.json')
    request=read(state['request']);library=read(state['library'])
    machine=library_scan.machine_identity([Path(p) for p in library['roots']])
    if machine!=library['machine_id']:raise ValueError('This selection belongs to another computer; rebuild its library and picker')
    session=read(state['session'])
    if session.get('status')!='confirmed':return {'status':'pending_selection','edited':False}
    errors=S.validate_confirmed_session(request,library,session,S.file_hash(state['request']),S.file_hash(state['library']))
    if errors:raise ValueError('; '.join(errors))
    if not state.get('plan') or not state.get('base'):
        state['status']='choices_confirmed';save(work/'workflow.json',state)
        return {'status':'choices_confirmed','edited':False,'reason':'Resolved media plan and base project are not provided'}
    resolved=selection_plan.assemble_plan(read(state['plan']),request,library,session,S.file_hash(state['request']),S.file_hash(state['library']))
    plan_path=work/'edit-plan.selected.json';save(plan_path,resolved)
    build=work/'build';capcut_native.build_files(plan_path,state['base'],state['library'],build)
    state.update(status='built',build=str(build),selected_plan=str(plan_path),capcut_open_verified=False)
    if install:
        installed=capcut_native.install_build(build,state['base'],confirmed_closed)
        state.update(status='installed',installation=installed)
    save(work/'workflow.json',state)
    return {'status':state['status'],'build':str(build),'capcut_open_verified':False}


def main():
    ap=argparse.ArgumentParser(description=__doc__);sub=ap.add_subparsers(dest='command',required=True)
    p=sub.add_parser('setup');p.add_argument('--state-dir');p.add_argument('--root',action='append');p.add_argument('--cache-root',action='append');p.add_argument('--refresh',action='store_true')
    p=sub.add_parser('prepare');p.add_argument('--request',required=True);p.add_argument('--work',required=True);p.add_argument('--state-dir');p.add_argument('--root',action='append');p.add_argument('--plan');p.add_argument('--base');p.add_argument('--roughcut');p.add_argument('--reuse-selection')
    for command in ('launch','resume','run'):
        p=sub.add_parser(command);p.add_argument('--work',required=True)
        if command in ('launch','run'):p.add_argument('--no-open',action='store_true')
        if command in ('resume','run'):
            p.add_argument('--install',action='store_true');p.add_argument('--confirmed-closed',action='store_true')
        if command=='run':p.add_argument('--timeout',type=float,default=0,help='0 keeps the local worker waiting for explicit human confirmation')
    a=ap.parse_args()
    try:
        if a.command=='setup':
            _,_,result=library_setup.load_or_setup(a.state_dir,a.root,refresh=a.refresh,caches=a.cache_root)
        elif a.command=='prepare':result=prepare(a.request,a.work,a.state_dir,a.root,a.plan,a.base,a.roughcut,a.reuse_selection)
        elif a.command=='launch':result=launch(a.work,a.no_open)
        elif a.command=='resume':result=resume(a.work,a.install,a.confirmed_closed)
        else:
            if a.timeout<0:raise ValueError('Timeout must be nonnegative')
            info=launch(a.work,a.no_open);print(json.dumps({'status':'pending_selection','url':info['url']},ensure_ascii=False),flush=True)
            deadline=time.monotonic()+a.timeout if a.timeout else None
            while True:
                state=read(Path(a.work)/'workflow.json')
                if Path(state['session']).exists() and read(state['session']).get('status')=='confirmed':break
                if deadline and time.monotonic()>=deadline:
                    print(json.dumps({'status':'pending_selection','edited':False}));return
                time.sleep(1)
            result=resume(a.work,a.install,a.confirmed_closed)
        print(json.dumps(result,ensure_ascii=False),flush=True)
    except (OSError,ValueError) as exc:
        print(json.dumps({'status':'error','error':str(exc)},ensure_ascii=False),file=sys.stderr);raise SystemExit(1)


if __name__=='__main__':main()
