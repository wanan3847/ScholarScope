/* Local PPTX rendering: text, shapes and charts remain editable in PowerPoint. */
import fs from "node:fs";
import PptxGenJS from "../frontend/node_modules/pptxgenjs/dist/pptxgen.es.js";

const [input, output] = process.argv.slice(2);
if (!input || !output) process.exit(2);
const view = JSON.parse(fs.readFileSync(input, "utf8"));
const { slides, theme } = view.data;
const pptx = new PptxGenJS();
pptx.layout = "LAYOUT_WIDE";
pptx.author = "ScholarScope";
pptx.subject = "Project evidence draft; review sources before presenting.";
pptx.title = view.label;
pptx.company = "Research workspace";
pptx.lang = "zh-CN";
pptx.theme = { headFontFace: theme.heading_font, bodyFontFace: theme.font, lang: "zh-CN" };
for (let index = 0; index < slides.length; index++) {
  const item = slides[index], s = pptx.addSlide();
  s.background = { color: theme.background };
  s.addShape(pptx.ShapeType.line, { x: 0.65, y: 0.65, w: 12, h: 0, line: {color:theme.ink,width:.5,dash:'dash'} });
  s.addText("SCHOLARSCOPE / RESEARCH", { x: 0.65, y: 0.26, w: 9, h: .2, color: theme.ink, fontSize: 9, fontFace: theme.font, margin: 0 });
  s.addText(`${index+1} / ${slides.length}`, { x: 11.4, y: .26, w: 1.25, h: .2, align:'right', color:theme.ink, fontSize:9, margin:0 });
  const titleSlide = item.layout === "title";
  s.addText(item.title, { x:.7,y:titleSlide?1.9:.95,w:11.9,h:titleSlide?1.8:1.15,fontFace:theme.heading_font,fontSize:titleSlide?36:28,bold:true,color:theme.ink,margin:0,breakLine:false,fit:'shrink',valign:'mid' });
  if (item.subtitle) s.addText(item.subtitle,{x:.7,y:titleSlide?4.2:2.15,w:11.8,h:.6,color:theme.accent,fontSize:18,fontFace:theme.font,margin:0,fit:'shrink'});
  const twoColumn = item.layout === "two_column";
  const startY = item.subtitle ? 2.95 : 2.45;
  const maxHeight = 6.55-startY;
  const rows = twoColumn ? Math.ceil(item.bullets.length/2) : item.bullets.length;
  const rowHeight = Math.min(1.25,maxHeight/Math.max(1,rows));
  for (let n=0;n<item.bullets.length && item.layout!=="chart";n++) {
    const b = item.bullets[n], col=twoColumn && n>=rows?1:0, row=twoColumn?n%rows:n;
    const width=twoColumn?5.6:11.7;
    const ids=(b.evidence_refs || (b.evidence_id?[b]:[])).map(r=>r.evidence_id);
    const numbers=[...new Set((item.citations || []).filter(c=>ids.includes(c.evidence_id)).map(c=>c.number || "?"))];
    const text=b.text+numbers.map(n=>` [${n}]`).join("");
    s.addText(text,{x:.8+col*6.1,y:startY+row*rowHeight,w:width,h:rowHeight-.12,fontFace:theme.font,fontSize:Math.min(21,item.bullets.length>6?16:20),color:theme.ink,margin:0,fit:'shrink',valign:'top',paraSpaceAfter:8,breakLine:false});
  }
  // Charts are inserted as Office chart objects, never flattened images.
  if (item.layout === "chart" && item.chart?.series?.length) {
    s.addChart(item.chart.type === "line" ? pptx.ChartType.line : pptx.ChartType.bar,
      item.chart.series.map(series=>({name:series.name,labels:item.chart.labels,values:series.values})),
      {x:.8,y:2.35,w:11.8,h:4.1,showTitle:false,showLegend:true,showValue:false,catAxisTitle:item.chart.x_label||"",valAxisTitle:item.chart.y_label||"",showCatName:false,showCatNameOnLegend:false,chartColors:[theme.accent,theme.ink],fontFace:theme.font});
  }
  const footer=(item.citations || []).slice(0,4).map(c=>`[${c.number || "?"}] ${c.title || "来源已删除"}${c.page?` · p.${c.page}`:" · abstract"}${c.valid?"":" · RECHECK"}`).join(" | ");
  if (footer) s.addText(footer,{x:.7,y:6.85,w:12,h:.34,fontSize:8,fontFace:theme.font,color:theme.ink,margin:0,fit:'shrink'});
  s.addNotes([item.notes || "", ...((item.citations || []).map(c=>`[${c.number || "?"}] ${c.title || ""}\n${c.page?`Page ${c.page}`:"Abstract source"}\nSource validation: ${c.valid?"current":"RECHECK"}; human review: ${c.confirmed?"confirmed":"pending"}\n${c.quote || ""}`))].join("\n\n"));
}
await pptx.writeFile({ fileName: output });
