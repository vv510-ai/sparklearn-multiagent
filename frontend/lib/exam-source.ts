import type { TextItem } from "pdfjs-dist/types/src/display/api";
import { isReading, type ExamKind, type ExamQuestion } from "./cet6-exams";

export const normalizeHeadings = (text: string) => text.replace(/Ⅲ/g,"III").replace(/Ⅱ/g,"II").replace(/Ⅳ/g,"IV").replace(/Ⅰ/g,"I").replace(/\u00a0/g," ").replace(/\r/g,"");

/** Preserve paragraph starts and labels while removing PDF line-width wrapping. */
export function pdfPageText(items: TextItem[]) {
  const lines: { y: number; x: number; text: string }[] = [];
  for (const item of items) {
    if (!item.str.trim()) continue;
    const previous = lines.at(-1);
    if (previous && Math.abs(previous.y-item.transform[5]) < 3) previous.text += " " + item.str;
    else lines.push({ y:item.transform[5], x:item.transform[4], text:item.str });
  }
  const filtered = lines.filter(line => !/^\s*\d{4}\s*年.*第\s*\d+\s*页/.test(line.text) && !/^\s*第\s*\d+\s*页.*共/.test(line.text));
  const gaps = filtered.slice(1).map((line,i)=>filtered[i].y-line.y).filter(gap=>gap>5&&gap<45).sort((a,b)=>a-b);
  const normal = gaps[Math.floor(gaps.length/2)] || 20;
  const left = Math.min(...filtered.map(line=>line.x));
  return normalizeHeadings(filtered.map((line,i)=>{
    if(!i)return line.text;
    const previous=filtered[i-1];
    const labeled=/^(?:Part\s+[IⅣⅢⅡVX]+|Section\s+[ABC]|Passage\s+(?:One|Two)|Directions\s*:|Questions\s+\d|\d{1,2}\s*[.．]|[A-Z]\s*[)）\]．])/i.test(line.text.trim());
    const gap=previous.y-line.y;
    const paragraph=gap>normal*1.35 || (line.x>left+12 && /[.!?。！？]["”’']?\s*$/.test(previous.text));
    return (labeled||paragraph?"\n\n":" ")+line.text;
  }).join("")).trim();
}

export function cutSection(raw: string, kind: ExamKind) {
  let text = normalizeHeadings(raw).split(/答案\s*速查/)[0];
  const roman = isReading(kind)?"III":kind==="listening"?"II":kind==="translation"?"IV":"I";
  const start = new RegExp(`Part\\s+${roman}\\b[^a-z]`,"i").exec(text);
  if(start)text=text.slice(start.index);
  const end = new RegExp(`Part\\s+${roman==="I"?"II":roman==="II"?"III":roman==="III"?"IV":"V"}\\b`,"i").exec(text);
  if(end)text=text.slice(0,end.index);
  if(kind==="reading_cloze"||kind==="reading_matching"||kind==="reading_careful"){
    const letter=kind==="reading_cloze"?"A":kind==="reading_matching"?"B":"C";
    const section=new RegExp(`Section\\s+${letter}\\b`,"i").exec(text);
    if(section)text=text.slice(section.index);
    const following=new RegExp(`Section\\s+${letter==="A"?"B":letter==="B"?"C":"D"}\\b`,"i").exec(text.slice(10));
    if(following)text=text.slice(0,following.index+10);
  }
  return text.trim();
}

export function sourceQuestion(source: string, q: ExamQuestion, kind: ExamKind): {stem:string; options:Record<string,string>} {
  if(q.number<36 && isReading(kind)) {
    // The 2024-06 Word export prints the I label as ID. The word and its
    // position agree with that edition's answer document; correct only this label.
    const section=cutSection(source,"reading_cloze").replace(/\bID\)\s*(?=illegally\b)/g,"I) ");
    const bank=section.match(/(?:^|\s)A[)）]\s*[\s\S]*/)?.[0] || "";
    const matches=[...bank.matchAll(/(?:^|\s)([A-O])[)）]\s*/g)];
    return {stem:`选词填空 · 第 ${q.number} 空`, options:Object.fromEntries(matches.map((m,i)=>[m[1],bank.slice(m.index!+m[0].length,matches[i+1]?.index??bank.length).replace(/\s+/g," ").trim()]))};
  }
  const start=new RegExp(`(?:^|\\s)(?:\\d{1,2}\\.\\s*)?${q.number}[.．]\\s*`).exec(source);
  if(!start) return {stem:`第 ${q.number} 题 · 请对照原卷`,options:{}};
  const tail=source.slice(start.index+start[0].length);
  const end=new RegExp(`(?:^|\\s)(?:\\d{1,2}\\.\\s*)?${q.number+1}[.．]\\s*|(?:^|\\n)\\s*(?:Part [IVX]+|Section [ABC]|Questions \\d|Passage (?:One|Two))`).exec(tail);
  const part=(end?tail.slice(0,end.index):tail).trim();
  if(q.number>=36&&q.number<=45&&isReading(kind)) return {stem:part.split(/(?:^|\n)\s*(?:\(?A[)）]|原文段落|📖)/)[0].replace(/\s+/g," ").trim(),options:{}};
  const matches=[...part.matchAll(/(?:^|\s)([A-D])[)）]\s*/g)],options:Record<string,string>={};
  for(let i=0;i<matches.length;i++){const m=matches[i];options[m[1]]=part.slice(m.index!+m[0].length,matches[i+1]?.index??part.length).replace(/\s+/g," ").trim();}
  return {stem:matches.length?part.slice(0,matches[0].index).replace(/\s+/g," ").trim()||`第 ${q.number} 题（问题在录音中）`:`第 ${q.number} 题 · 请对照原卷`,options};
}

export function passageView(source: string, kind: ExamKind, number: number) {
  if(!isReading(kind)) return {paragraphs:source.split(/\n\s*\n/).map(p=>p.replace(/\s+/g," ").trim()).filter(Boolean),directions:""};
  let text=source, directions="";
  if(kind==="reading_careful" || kind==="reading"&&number>=46){
    text=cutSection(source,"reading_careful");
    const passage=/Passage\s+Two\b/i.exec(text);
    if(passage)text=number>=51?text.slice(passage.index):text.slice(0,passage.index);
    text=text.split(new RegExp(`(?:^|\\s)(?:\\d{1,2}\\.\\s*)?${number>=51?51:46}[.．]\\s*`))[0];
  }else if(kind==="reading_matching"||kind==="reading"&&number>=36){
    text=cutSection(source,"reading_matching");
    // Some source editions put the ten statements before their A–R paragraphs.
    const labels=[...text.matchAll(/(?:^|\n)\s*\(?([A-R])[)）]\s*/g)];
    const start=labels.find(m=>m[1]==="A");
    if(start)text=text.slice(start.index);
    text=text.split(/(?:^|\s)(?:\d{1,2}\.\s*)?36[.．]\s*/)[0];
  }else if(kind==="reading_cloze"||kind==="reading"&&number<36){
    text=cutSection(source,"reading_cloze").split(/(?:^|\s)A[)）]\s*/)[0];
  }
  // Keep directions available without letting them dominate the reading surface.
  const paragraphs=text.split(/\n\s*\n/).map(p=>p.replace(/\s+/g," ").trim()).filter(Boolean);
  const visible=paragraphs.filter(p=>{
    if(/^(?:Part\s+[IVX]+|Section\s+[ABC]|Passage\s+(?:One|Two)|Questions\s+\d|Directions\s*:)/i.test(p)) {directions+=p+"\n";return false;}
    return true;
  });
  return { paragraphs: visible.length?visible:paragraphs, directions };
}
