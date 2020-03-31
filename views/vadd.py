from flask import *
from mysql import mysql

from sister import use_sister,SisterErrorMsg
import model

bp=Blueprint('add',__name__)

def proc_extpid(name_list):
    """ Convert share pattern to external pids.
    :param name_list: list of string which may contain share pattern
    :return: yields a list of [name, extpid or None]
    """
    cur=mysql.get_db().cursor()
    for nameline in name_list:
        name,at,share_hash=nameline.rpartition('@@')
        if not at: # '','','name'
            yield [share_hash, None]
        else: # 'name','@@','hash'
            if not share_hash:
                raise SisterErrorMsg(nameline+'：分享ID无效')

            cur.execute('''
                select uid,pid from projects where share_hash=%s
            ''',[share_hash])
            res=cur.fetchone()
            if not res:
                raise SisterErrorMsg(nameline+'：未找到分享ID')
            if res[0]==g.user.uid:
                raise SisterErrorMsg(nameline+'：不能分享给自己')

            yield [name,res[1]]


@bp.route('/add/zone',methods=['POST'])
@use_sister()
def add_zone():
    """
    INPUT:
         names: list of str
    """
    names=request.json['names']

    z_o,_=g.user.zones(need_list=False)
    z_o=z_o.get(None,[])
    if len(z_o)+len(names)>current_app.config['LIMIT_ZONES']:
        flash('课程数量超出限制','error')
        g.action_success=False
        return

    cur=mysql.get_db().cursor()
    z_onew=z_o
    for name in names:
        if len(name)>current_app.config['MAX_NAME_LENGTH']:
            flash('名称长度超出限制','error')
            g.action_success=False
            return

        cur.execute('''
            insert into zones (next_zid, name, uid) values (null, %s, %s)    
        ''',[name,g.user.uid])
        z_onew=z_onew+[cur.lastrowid]

    model.update_linkedlist(z_o,z_onew,'zones')

@bp.route('/add/project',methods=['POST'])
@use_sister()
def add_project():
    """
    INPUT:
        names: list of str
        parent_id: int
    """
    zid=int(request.json['parent_id'])
    try:
        names=list(proc_extpid(request.json['names']))
    except SisterErrorMsg as e:
        flash(e.msg,'error')
        g.action_success=False
        return

    if not g.user.check_zone(zid):
        flash('课程不存在或没有权限','error')
        g.action_success=False
        return

    p_o,_=g.user.projects(zid,need_list=False)
    p_o=p_o.get(zid,[])
    if len(p_o)+len(names)>current_app.config['LIMIT_PROJECTS_PER_ZONE']:
        flash('类别数量超出限制','error')
        g.action_success=False
        return

    already_extpids=set(g.user.imported_extpids())
    for name,extpid in names:
        if extpid:
            if g.user.ring>current_app.config['MAX_RING_FOR_SHARING']:
                flash('你所在的用户组不能导入共享','error')
                g.action_success=False
                return

            if extpid in already_extpids:
                flash(name+'：已经添加过了','error')
                g.action_success=False
                return
            else:
                already_extpids.add(extpid)


    cur=mysql.get_db().cursor()
    p_onew=p_o
    for name,extpid in names:
        if len(name)>current_app.config['MAX_NAME_LENGTH']:
            flash('名称长度超出限制','error')
            g.action_success=False
            return

        cur.execute('''
            insert into projects (next_pid, name, uid, zid, extpid) values (null, %s, %s, %s, %s)    
        ''',[name,g.user.uid,zid,extpid])
        p_onew=p_onew+[cur.lastrowid]

    model.update_linkedlist(p_o,p_onew,'projects')

@bp.route('/add/task',methods=['POST'])
@use_sister()
def add_task():
    """
    INPUT:
        names: list of str
        parent_id: int
        task_due_first: int or null
        task_due_delta: int (days) or null
    """
    names=request.json['names']
    pid=int(request.json['parent_id'])
    task_due_first=request.json['task_due_first']
    task_due_delta=int(request.json['task_due_delta'])
    if task_due_first is not None:
        task_due_first=int(task_due_first)

    if not 0<=task_due_delta<1000:
        flash('截止日期间隔错误','error')
        g.action_success=False
        return

    if not g.user.check_project(pid):
        flash('类别不存在或没有权限','error')
        g.action_success=False
        return

    t_o,_=g.user.tasks(pid,need_list=False)
    t_o=t_o.get(pid,[])
    if len(t_o)+len(names)>current_app.config['LIMIT_TASKS_PER_PROJECT']:
        flash('任务数量超出限制','error')
        g.action_success=False
        return

    cur=mysql.get_db().cursor()
    t_onew=t_o
    for idx,name in enumerate(names):
        if len(name)>current_app.config['MAX_NAME_LENGTH']:
            flash('名称长度超出限制','error')
            g.action_success=False
            return

        cur.execute('''
            insert into tasks (next_tid, name, uid, pid, status, due) values (null, %s, %s, %s, %s, %s)     
        ''',[name,g.user.uid,pid,'placeholder' if len(names)>1 else 'active',None if task_due_first is None else (task_due_first+idx*86400*task_due_delta)])
        t_onew=t_onew+[cur.lastrowid]

    model.update_linkedlist(t_o,t_onew,'tasks')

@bp.route('/market/search_project',methods=['POST'])
@use_sister(may_fallback=False,require_ring=3)
def market_search_project():
    """
    INPUT:
        term: str
    OUTPUT:
        error: str or null
        error_msg: str if error occurs
        result: list of {name,share_hash,pid}
        tasks: list of tasks
    """

    term=str(request.json['term'])

    if not term:
        raise SisterErrorMsg('请输入搜索词')
    if len(term)<2:
        raise SisterErrorMsg('请输入至少两个字')

    cur=mysql.get_db().cursor()
    cur.execute('''
        select name,share_hash,share_name,pid from projects where match(share_name) against (%s in natural language mode) and share_hash is not null limit 0,25
    ''',[term])

    res=[{
        'name': name,
        'share_hash': ''+share_hash, # will intentionally die here if share_hash is None
        'share_name': share_name,
        'pid': pid,
    } for name,share_hash,share_name,pid in cur.fetchall()]

    pids=[r['pid'] for r in res]
    if pids:
        tasks_o,tasks_li=g.user.tasks(pids,bypass_permission=True)
    else:
        tasks_o=[]
        tasks_li={}

    return {
        'error': None,
        'result': res,
        'tasks_o': tasks_o,
        'tasks_li': tasks_li,
    }