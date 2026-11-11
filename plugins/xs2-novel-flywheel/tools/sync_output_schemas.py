"""Keep model-visible JSON contracts identical to node validators, without reformatting workflows."""
import argparse
import json
from pathlib import Path
import re

BLOCK=re.compile(r'<OUTPUT_SCHEMA>\s*([\s\S]*?)\s*</OUTPUT_SCHEMA>')


def sync_file(path,write=False):
    path=Path(path);raw=path.read_bytes();bom=raw.startswith(b'\xef\xbb\xbf')
    text=raw.decode('utf-8-sig');definition=json.loads(text);replacements={};counts={};changed=0
    for node in definition.get('nodes',[]):
        schema=node.get('node_params',{}).get('json_output_schema')
        if node.get('node_type')!='agent' or not schema:continue
        old=node.get('first_message','');matches=BLOCK.findall(old)
        if len(matches)>1:raise ValueError(f'{path}: {node["id"]} has multiple output schema blocks')
        if matches:
            try:
                if json.loads(matches[0])==schema:continue
            except ValueError:pass
        block='<OUTPUT_SCHEMA>\n'+json.dumps(schema,ensure_ascii=False,indent=2)+'\n</OUTPUT_SCHEMA>'
        new=BLOCK.sub(lambda _:block,old,count=1) if matches else (old+
            '\n【返回格式：以下schema与程序验证器一致，只约束JSON结构，不规定小说风格】\n'+block+
            '\n仅输出该结构的JSON对象，不用Markdown围栏；说明放入指定文字字段，布尔字段只用true/false，数组字段即使只有一项也须用数组。')
        key=json.dumps(old,ensure_ascii=False);value=json.dumps(new,ensure_ascii=False)
        if key in replacements and replacements[key]!=value:
            raise ValueError(f'{path}: identical messages require different schema edits; review manually')
        replacements[key]=value;counts[key]=counts.get(key,0)+1;changed+=1
    for old,new in replacements.items():
        if text.count(old)!=counts[old]:raise ValueError(f'{path}: message literal is not uniquely scoped to its nodes')
        text=text.replace(old,new)
    if write and changed:path.write_bytes((b'\xef\xbb\xbf' if bom else b'')+text.encode('utf-8'))
    return changed


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--write',action='store_true')
    args=parser.parse_args();root=Path(__file__).resolve().parents[1]/'resources/workflows'
    changed={p.parent.name:count for p in sorted(root.glob('*/definition.json')) if (count:=sync_file(p,write=args.write))}
    print(json.dumps({'updated' if args.write else 'out_of_sync':changed},ensure_ascii=False))
    if changed and not args.write:raise SystemExit(1)


if __name__=='__main__':main()
