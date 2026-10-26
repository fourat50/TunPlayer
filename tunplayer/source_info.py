"""Provider account metadata, deliberately separated from connection secrets."""
from datetime import datetime
import math
import time
from urllib.parse import urlsplit, urlunsplit, parse_qs
from pathlib import Path


def account_connection(config):
    if config.get('type')=='xtream':
        return {key:config.get(key,'') for key in ('server','username','password')}
    if config.get('type')=='m3u':
        try:
            url=urlsplit(config.get('location',''));query=parse_qs(url.query)
            if url.scheme in ('http','https') and url.path.endswith('/get.php') and query.get('username') and query.get('password'):
                return dict(server=urlunsplit((url.scheme,url.netloc,url.path[:-8],'','')),
                            username=query['username'][0],password=query['password'][0])
        except ValueError:pass
    return None


def timestamp(value):
    try:
        result=float(value)
        if not math.isfinite(result) or result<=0:return None
        datetime.fromtimestamp(result)
        return result
    except (TypeError,ValueError,OverflowError,OSError):return None


def normalize_account(data,now=None):
    if not isinstance(data,dict) or not isinstance(data.get('user_info'),dict):
        raise ValueError('Missing account information')
    user=data['user_info'];server=data.get('server_info')
    server=server if isinstance(server,dict) else {}
    # Whitelist: never persist provider passwords, messages or arbitrary URLs.
    result={'checked_at':time.time() if now is None else now,'error':'',
            'status':str(user.get('status') or '')[:40],
            'authenticated':str(user.get('auth',''))=='1',
            'expires_at':timestamp(user.get('exp_date')),
            'expiry_unlimited':'exp_date' in user and (user['exp_date'] is None or str(user['exp_date']).lower() in ('','null','0')),
            'created_at':timestamp(user.get('created_at')),
            'trial':str(user['is_trial'])=='1' if 'is_trial' in user else None,
            'timezone':str(server.get('timezone') or '')[:80]}
    for field in ('active_cons','max_connections'):
        try:result[field]=max(0,int(user[field]))
        except (KeyError,ValueError,TypeError,OverflowError):result[field]=None
    formats=user.get('allowed_output_formats',[])
    result['formats']=[v for v in formats[:12] if isinstance(v,str) and v.isalnum() and len(v)<16] if isinstance(formats,list) else []
    return result


def fetch_account(config,previous=None,now=None):
    from .core import request_xtream
    connection=account_connection(config)
    if not connection:return {}
    try:return normalize_account(request_xtream(connection,None),now)
    except Exception:
        return dict(previous or {},attempted_at=time.time() if now is None else now,
                    error='Informations du compte indisponibles. Réessayez l’actualisation.')


def date_text(value):
    value=timestamp(value)
    return datetime.fromtimestamp(value).strftime('%d/%m/%Y à %H:%M') if value else 'Non communiquée'


def subscription(account,now=None):
    now=time.time() if now is None else now
    status=str(account.get('status','')).lower()
    expiry=timestamp(account.get('expires_at'))
    if status in ('expired','disabled','banned') or (expiry and expiry<=now):
        return ('Expiré' if status not in ('disabled','banned') else 'Désactivé'), 'expired'
    if expiry:
        days=math.ceil((expiry-now)/86400)
        return f'Expire le {datetime.fromtimestamp(expiry).strftime("%d/%m/%Y")} · {days} j', 'soon' if days<=7 else 'active'
    if account.get('expiry_unlimited'):return 'Sans date limite', 'active' if account.get('authenticated') else 'unknown'
    return 'Expiration non communiquée', 'unknown'


def safe_location(config):
    value=config.get('server') if config.get('type')=='xtream' else config.get('location','')
    try:
        parsed=urlsplit(value or '')
        if parsed.scheme in ('http','https'):
            host=parsed.hostname or ''
            if ':' in host:host='['+host+']'
            return f'{parsed.scheme}://{host}'+(f':{parsed.port}' if parsed.port else '')
        return Path(value or '').name or 'Source locale'
    except (ValueError,TypeError):return 'Adresse enregistrée'


def account_fields(config,account,counts=None):
    state={'active':'Actif','expired':'Expiré','disabled':'Désactivé','banned':'Suspendu'}.get(str(account.get('status','')).lower(),'Non communiqué')
    if account.get('error'):state+=' · dernière vérification indisponible'
    rows=[('Type de source','Xtream Codes' if config.get('type')=='xtream' else 'Playlist M3U'),
          ('Serveur / fichier',safe_location(config)),('État du compte',state),
          ('Fin de l’abonnement',date_text(account.get('expires_at')) if account.get('expires_at') else ('Sans date limite' if account.get('expiry_unlimited') else 'Non communiquée par la source')),
          ('Création du compte',date_text(account.get('created_at'))),
          ('Formule','Essai' if account.get('trial') is True else ('Standard' if account.get('trial') is False else 'Non communiquée')),
          ('Connexions actives / autorisées',f'{account.get("active_cons") if account.get("active_cons") is not None else "—"} / {account.get("max_connections") if account.get("max_connections") is not None else "—"}'),
          ('Formats disponibles',', '.join(account.get('formats',[])) or 'Non communiqués'),
          ('Fuseau du fournisseur',account.get('timezone') or 'Non communiqué'),
          ('Dernière vérification du compte',date_text(account.get('checked_at')))]
    if config.get('username'):rows.insert(2,('Identifiant',config['username']))
    if counts is not None:
        rows.append(('Catalogue local',f'{counts.get("live",0)} chaînes · {counts.get("movie",0)} films · {counts.get("series",0)} séries · {counts.get("episode",0)} épisodes'))
    return rows
