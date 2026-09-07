import importlib.util,sys,json,tempfile,os
from pathlib import Path
p=Path('scripts/dev_deploy.py').resolve();spec=importlib.util.spec_from_file_location('deploy',p);d=importlib.util.module_from_spec(spec);sys.modules['deploy']=d;spec.loader.exec_module(d)
d.RUNTIME_ROOT.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(dir=d.RUNTIME_ROOT) as tmp:
 folder=Path(tmp);env=folder/'.env.prep'; env.write_text('''# syntax fixture, no provider secrets
ORIGIN=example.invalid
URL="https://${ORIGIN}/api"
LITERAL='pa$$word#literal'
EXPORTED="a b # c"
EMPTY=
BARE=value # comment
''');env.chmod(0o600);before=d.sha256_file(env);v=d.read_env(env)
 assert v=={'ORIGIN':'example.invalid','URL':'https://example.invalid/api','LITERAL':'pa$$word#literal','EXPORTED':'a b # c','EMPTY':'','BARE':'value'}
 assert d.sha256_file(env)==before
 optional=env.with_name('.env.prep.optional');optional.write_text('SECONDARY="${ORIGIN}/path"\n');optional.chmod(0o600)
 assert d.operator_environment(env)['SECONDARY']=='example.invalid/path'
 optional.write_text('ORIGIN=conflict.invalid\n')
 try:d.operator_environment(env)
 except d.DeployError as e:assert str(e)=='PREP_ENV_OWNERSHIP_CONFLICT'
 else:raise AssertionError('optional duplicate keys must fail')
 optional.unlink()
 d.RUNTIME_ROOT=folder/'runtime';d.docker_platform=lambda:'linux/amd64'
 source={'POC_PUBLIC_ORIGIN':'http://prep.invalid:39083','POC_RUNTIME_HTTP_PROXY':'http://proxy.invalid:8080','NO_PROXY':'example.invalid','HTTP_PROXY':'http://proxy.invalid:8080'}
 creds={k:'synthetic-'+k.lower() for k in d.read_json(d.ENV_CONTRACT)['ownership']['GENERATED']}
 derived,values=d.write_derived_environment(source,d.PREP_39083,'a'*40,state='EXISTING',preserved_runtime=creds)
 assert all(values[k]==v for k,v in creds.items())
 assert 'localhost' in values['NO_PROXY'] and 'neo4j' in values['POC_RUNTIME_NO_PROXY']
 actual=d.read_env(derived)
 assert {k:v for k,v in actual.items() if k!="COMPOSE_PROJECT_NAME"}=={k:v for k,v in values.items() if k!="COMPOSE_PROJECT_NAME"}
 assert values["COMPOSE_PROJECT_NAME"]==d.PREP_39083.project
 assert derived.stat().st_mode&0o777==0o600
 try:d.write_derived_environment(source,d.PREP_39083,'a'*40,state='EXISTING')
 except d.DeployError as e:assert str(e)=='EXISTING_STATE_CREDENTIALS_REQUIRED'
 else:raise AssertionError('existing credentials must never regenerate')
 try:d.write_derived_environment({**source,'NEO4J_PASSWORD':'different'},d.PREP_39083,'a'*40,state='EXISTING',preserved_runtime=creds)
 except d.DeployError as e:assert str(e)=='PREP_GENERATED_VALUE_DRIFT'
 else:raise AssertionError('credential drift must fail')
 print('ENV_CONTRACT_REGRESSION=PASS quoting/interpolation/literal/unchanged/private/proxy/preserved_credentials/drift')
