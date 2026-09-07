from pathlib import Path
import tempfile,subprocess,importlib.util,sys,json,os
spec=importlib.util.spec_from_file_location('d','scripts/dev_deploy.py');d=importlib.util.module_from_spec(spec);sys.modules['d']=d;spec.loader.exec_module(d)
d.RUNTIME_ROOT.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(dir=d.RUNTIME_ROOT) as name:
 tmp=Path(name);d.RUNTIME_ROOT=tmp/'generated';d.docker_platform=lambda:'linux/amd64'
 source={'POC_PUBLIC_ORIGIN':'http://synthetic.invalid:39083'}
 for key in d.read_json(d.ENV_CONTRACT)['ownership']['CORE_REQUIRED']:
  source.setdefault(key,'synthetic-value')
 creds={k:'synthetic-local-only-'+k for k in d.read_json(d.ENV_CONTRACT)['ownership']['GENERATED']}
 env,values=d.write_derived_environment(source,d.PREP_39083,d.git_head(),state='EXISTING',preserved_runtime=creds)
 old=tmp/'old';old.mkdir();base=old/'compose.yaml';overlay=old/'artifact.yaml'
 for p,ref in [(base,'2bd5494:deploy/poc/docker-compose.poc.yaml'),(overlay,'2bd5494:deploy/prep39083/docker-compose.artifact.yaml')]:p.write_bytes(subprocess.check_output(['git','show',ref],cwd=os.environ.get('DATARIVER_BASELINE_REPO',os.getcwd())))
 def render(files):return json.loads(d.run(['docker','compose','-p',d.PREP_39083.project,'--env-file',str(env),*[x for p in files for x in ('-f',str(p))],'config','--format','json']).stdout)
 before=render([base,overlay]);after=render([d.BASE_COMPOSE]);d.validate_compose(d.PREP_39083,d.compose_prefix(d.PREP_39083,env),d.source_image(d.git_head()))
 assert before['networks']==after['networks'] and before['volumes']==after['volumes']
 for service in before['services']:
  a=before['services'][service];b=after['services'][service]
  for k in ['build','image','pull_policy']:a.pop(k,None);b.pop(k,None)
  if service=='pgvector':
   for config in (a,b):
    for mount in config['volumes']:
     if mount['type']=='bind':mount['source']='PATH_ONLY/postgres-init'
  assert a==b, service
 print('COMPOSE_BASELINE_PARITY=PASS services/env/ports/networks/volumes/resources/security; differences=source_image_build_and_schema_path')
