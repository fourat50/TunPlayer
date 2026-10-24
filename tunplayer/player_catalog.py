"""Bounded, cancellable catalogue reads for browsing without leaving the player."""
from .core import Library,SourceError
from .catalog import fold
from .jobs import SnapshotCache


def neighbors(library,identity):
    current=library.channel(identity)
    result={'previous':None,'next':None}
    if not current:return result
    if current['kind']=='episode' and not current['parent_id']:return result
    if current['kind']=='episode' and current['parent_id']:
        where='parent_id=?';args=[current['parent_id']]
        columns=('season','episode_num','name','id')
    else:
        where,args=library._filter(view=current['kind'],source_id=current['source_id'],group=current['group_name'])
        columns=('search_name','id')
        if current['kind']=='series':where+=" AND url NOT LIKE 'xtream-series:%'"
    key='('+','.join(columns)+')';marks='('+','.join('?' for _ in columns)+')'
    values=[current[column] for column in columns]
    for direction,operator,order in [('previous','<','DESC'),('next','>','ASC')]:
        ordering=','.join(f'{column} {order}' for column in columns)
        row=library.db.execute(f'SELECT * FROM channels WHERE {where} AND {key}{operator}{marks} ORDER BY {ordering} LIMIT 1',(*args,*values)).fetchone()
        result[direction]=dict(row) if row else None
    return result


class PlayerCatalog:
    def __init__(self,path):self.path=path;self.groups=SnapshotCache(limit=6)

    def snapshot(self,request,cancel):
        if cancel.is_set():return None
        library=Library(self.path,read_only=True)
        library.db.set_progress_handler(lambda:int(cancel.is_set()),1000)
        try:
            result=dict(neighbors=neighbors(library,request['current_id']),rows=[],groups=[],total=0,page=0,parent=None)
            if not request.get('opened'):return result
            kind=request['kind'];source=request['source_id']
            if kind not in ('live','movie','series'):raise SourceError('Type de contenu invalide.')
            group_key=dict(kind=kind,source=source,revision=request.get('revision',0))
            groups=self.groups.get(group_key)
            if groups is None:
                groups=library.group_counts(view=kind,source_id=source)
                if not cancel.is_set():self.groups.put(group_key,groups)
            result['groups']=groups
            parent=library.channel(request.get('series_id')) if kind=='series' and request.get('series_id') else None
            if parent and (parent['kind']!='series' or parent['source_id']!=source):parent=None
            result['parent']=parent
            if parent:
                where='parent_id=?';args=[parent['id']]
                for term in fold(request.get('search','')).split():
                    where+=' AND instr(search_name,?)>0';args.append(term)
                columns=('season','episode_num','name','id')
            else:
                where,args=library._filter(view=kind,source_id=source,group=request.get('group'),search=request.get('search',''))
                columns=('search_name','id')
            total=library.db.execute(f'SELECT COUNT(*) FROM channels WHERE {where}',args).fetchone()[0]
            size=40;page=max(0,int(request.get('page',0)))
            current=library.channel(request['current_id'])
            if request.get('focus') and current and library.db.execute(f'SELECT 1 FROM channels WHERE {where} AND id=?',(*args,current['id'])).fetchone():
                key='('+','.join(columns)+')';marks='('+','.join('?' for _ in columns)+')'
                rank=library.db.execute(f'SELECT COUNT(*) FROM channels WHERE {where} AND {key}<{marks}',(*args,*(current[column] for column in columns))).fetchone()[0]
                page=rank//size
            page=min(page,max(0,(total-1)//size))
            order=','.join(columns)
            rows=[dict(row) for row in library.db.execute(f'SELECT * FROM channels WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?',(*args,size,page*size))]
            result.update(rows=rows,total=total,page=page)
            return result
        finally:library.close()
