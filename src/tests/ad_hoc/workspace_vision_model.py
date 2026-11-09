"""Actual local vision on an embedded scientific chart, with known labels/trend."""
import io,json,os,tempfile
from pathlib import Path
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.utils import ImageReader
from PIL import Image,ImageDraw
from workspace.store import WorkspaceStore
from workspace.documents import ObjectStore,attach_pdf
from workspace import charts
out=Path('.cache/ai-vision');out.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='research-vision-') as directory:
    os.environ['SCHOLARSCOPE_WORKSPACE_DIR']=directory
    s=WorkspaceStore('sqlite:///'+str(Path(directory)/'db'));p=s.create_project('vision-check','Vision validation')
    paper=s.add_paper(p['id'],'vision-check',{'title':'Controlled plot: increasing porosity with depth'})
    image=Image.new('RGB',(700,500),'white');d=ImageDraw.Draw(image)
    d.line((100,60,100,400,620,400),fill='black',width=4)
    d.text((280,440),'Depth (m)',fill='black',font_size=28);d.text((5,15),'Porosity (%)',fill='black',font_size=28)
    d.text((80,405),'100',fill='black',font_size=22);d.text((570,405),'300',fill='black',font_size=22)
    d.line((110,350,300,240,580,90),fill='blue',width=6)
    blob=io.BytesIO();c=Canvas(blob);c.drawImage(ImageReader(image),40,300,width=500,height=350);c.drawString(40,280,'Figure 1. Controlled example: porosity rises as depth increases.');c.save()
    doc=attach_pdf(s,ObjectStore(),p['id'],'vision-check',paper['id'],'plot.pdf',blob.getvalue());page=doc['data']['pages'][0]
    result=charts.element_analysis(s,p['id'],'vision-check',doc['id'],1,'figure',page['figures'][0]['id'],visual=True)
    (out/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result['visual_analysis'],ensure_ascii=False,indent=2))
    assert result['visual_analysis']['status']=='needs_human_review'
    assert not s.items(p['id'],'vision-check','evidence'), 'Visual guesses became verified evidence'
