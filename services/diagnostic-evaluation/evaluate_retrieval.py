"""Reproducible offline ranking checks; fixture vectors never imply model accuracy."""
import argparse
import importlib.util
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('semantic_vectors',ROOT/'ProjectServer/plane/knowledge/semantic_vectors.py')
vectors=importlib.util.module_from_spec(spec);spec.loader.exec_module(vectors)

def evaluate(dataset):
    cases=[]
    for case in dataset['cases']:
        provenance=case.get('provenance')
        if provenance not in {'synthetic','real'}:raise ValueError('Every case must explicitly declare synthetic or real provenance')
        eligible=[doc for doc in dataset['documents'] if doc['project']==case['project'] and doc['published'] and doc['version']==doc['active_version']]
        terms=set(re.findall(r'[A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,}',case['query'].strip()))
        for token in list(terms):
            if re.fullmatch(r'[\u4e00-\u9fff]+',token) and len(token)>2:terms.update(token[i:i+2] for i in range(len(token)-1))
        terms=sorted(terms,key=len,reverse=True)[:24]
        keyword=[doc['id'] for doc in eligible if any(term.lower() in (doc['title']+'\n'+doc['text']).lower() for term in terms)]
        try:
            ranked=sorted([(vectors.cosine(case['vector'],doc['vector']),doc['id']) for doc in eligible],key=lambda row:(-row[0],row[1]))
            semantic=[id for score,id in ranked if score>=0.25][:3]
        except ValueError:semantic=[]
        cases.append({'id':case['id'],'provenance':provenance,'expected':case['expected'],'keyword':keyword,'semantic':semantic})
    groups={}
    for provenance in ['synthetic','real']:
        rows=[row for row in cases if row['provenance']==provenance]
        groups[provenance]={'case_count':len(rows),'status':'evaluated' if rows else 'no_dataset'}
        for method in ['keyword','semantic']:
            answerable=[row for row in rows if row['expected']]
            recall=sum(bool(set(row['expected'])&set(row[method][:3])) for row in answerable)/len(answerable) if answerable else None
            mrr=sum(next((1/(rank+1) for rank,id in enumerate(row[method][:3]) if id in row['expected']),0) for row in answerable)/len(answerable) if answerable else None
            groups[provenance][method]={'recall_at_3':recall,'mrr_at_3':mrr,'abstention_correct':sum(not row[method] for row in rows if not row['expected'])}
    return {'schema_version':1,'embedding_source':dataset['embedding_source'],'external_calls':0,
            'limitations':['Fixture vectors validate retrieval mechanics only.','Lexical baseline follows production whole tokens plus Chinese bigrams.','No diagnostic accuracy or real embedding quality is measured.'],
            'groups':groups,'cases':cases}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--dataset',type=Path,default=Path(__file__).with_name('synthetic-retrieval.json'));parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();report=evaluate(json.loads(args.dataset.read_text()));args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({'output':str(args.output),'groups':report['groups'],'external_calls':0}))
if __name__=='__main__':main()
