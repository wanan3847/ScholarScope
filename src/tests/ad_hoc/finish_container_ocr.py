"""Finish this task's slow image build/check, then release its check VM."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import subprocess
import time

parser=argparse.ArgumentParser()
parser.add_argument('--builder-pid',type=int,required=True)
args=parser.parse_args()
ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'.cache/container-ocr-verification'
OUT.mkdir(parents=True,exist_ok=True)
ENV={**os.environ,'DOCKER_HOST':'unix://'+str(Path.home()/'.colima/scholarscope-check/docker.sock'),
    'DOCKER_CONFIG':str(ROOT/'.cache/docker-check')}
state={'status':'waiting_build','profile':'scholarscope-check'}


def checkpoint(status,**extra):
    state.update(status=status,updated_at=datetime.now(timezone.utc).isoformat(),**extra)
    (OUT/'status.json').write_text(json.dumps(state,ensure_ascii=False,indent=2))


def builder_running():
    r=subprocess.run(['ps','-p',str(args.builder_pid),'-o','command='],capture_output=True,text=True,timeout=3)
    return 'docker build -t scholarscope:check' in r.stdout


def docker(command,log,timeout):
    with (OUT/log).open('w') as output:
        r=subprocess.run(['docker',*command],cwd=ROOT,env=ENV,stdout=output,stderr=output,timeout=timeout)
    if r.returncode:raise RuntimeError(log+' failed; inspect its recorded output')


try:
    checkpoint('waiting_build')
    deadline=time.monotonic()+90*60
    while builder_running():
        if time.monotonic()>deadline:raise TimeoutError('Initial build did not finish within the check budget')
        time.sleep(10)
    if 'Successfully tagged scholarscope:check' not in (ROOT/'.cache/container-build-ocr.log').read_text():
        raise RuntimeError('Initial build failed; the old image will not be used as OCR verification')
    checkpoint('building_latest_source')
    docker(['build','-t','scholarscope:check','.'],'final-build.log',1800)
    image=subprocess.run(['docker','image','inspect','scholarscope:check','--format','{{.Id}}'],env=ENV,capture_output=True,text=True,check=True,timeout=10).stdout.strip()
    checkpoint('testing',image=image)
    run=['run','--rm','--read-only','--tmpfs','/tmp:rw,size=512m',
        '--tmpfs','/data:rw,size=256m,uid=10001,gid=10001,mode=0700',
        '-e','SCHOLARSCOPE_DISABLE_AI=1','-e','SCHOLARSCOPE_DISABLE_EMBEDDINGS=1','--entrypoint','python','scholarscope:check']
    docker([*run,'-m','pytest','tests/','-q','-p','no:cacheprovider'],'regression.log',300)
    scan_code='''import io,json,subprocess,tempfile
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.utils import ImageReader
from workspace.documents import parse_pdf
langs=subprocess.run(['tesseract','--list-langs'],capture_output=True,text=True,check=True).stdout
assert 'chi_sim' in langs and 'eng' in langs
font=next(Path('/usr/share/fonts').rglob('NotoSansCJK-Regular.ttc'))
image=Image.new('RGB',(1600,240),'white')
ImageDraw.Draw(image).text((60,80),'神经网络预测测井孔隙度，样本120个。',font=ImageFont.truetype(str(font),48),fill='black')
blob=io.BytesIO();canvas=Canvas(blob);canvas.drawImage(ImageReader(image),50,600,width=500,height=75);canvas.save()
parsed=parse_pdf(blob.getvalue());page=parsed['pages'][0];text=''.join(page['text'].split())
assert parsed['ocr_pages']==1 and '测井' in text and '孔隙度' in text and '120' in text
assert page['ocr_language']=='eng+chi_sim' and page['spans']
print(json.dumps({'status':'PASS','text':text,'language':page['ocr_language'],'confidence':page['ocr_confidence']},ensure_ascii=False))
'''
    docker([*run,'-c',scan_code],'chinese-scan.log',90)
    checkpoint('passed',message='Latest image regression and actual Chinese scanned-page OCR passed.')
except Exception as error:
    checkpoint('failed',error_type=type(error).__name__,message=str(error))
finally:
    # Only the still-running, explicitly identified build owned by this task.
    if builder_running():os.kill(args.builder_pid,15)
    try:
        with (OUT/'stop-vm.log').open('w') as output:
            r=subprocess.run(['colima','-p','scholarscope-check','stop'],stdout=output,stderr=output,timeout=60)
        checkpoint(state['status'],vm_stop_exit_code=r.returncode)
    except Exception as error:checkpoint(state['status'],vm_stop_error=type(error).__name__)
