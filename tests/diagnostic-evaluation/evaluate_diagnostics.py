"""Score supplied diagnostic outputs against explicitly labelled cases; never generate answers."""
import argparse
import json
from pathlib import Path

def evaluate(dataset,outputs):
    supplied={row['case_id']:row for row in outputs['outputs']};cases=[]
    for case in dataset['cases']:
        if case.get('provenance') not in {'synthetic','real'}:raise ValueError('Case provenance required')
        actual=supplied.get(case['id'])
        if actual is None:
            cases.append({'case_id':case['id'],'provenance':case['provenance'],'status':'missing_output'});continue
        answer=actual.get('answer','');citations=set(actual.get('citations',[]));allowed=set(case.get('allowed_citations',[]))
        missing=[term for term in case.get('required_terms',[]) if term.casefold() not in answer.casefold()]
        forbidden=[term for term in case.get('forbidden_terms',[]) if term.casefold() in answer.casefold()]
        unexpected=sorted(citations-allowed)
        cases.append({'case_id':case['id'],'provenance':case['provenance'],'status':'evaluated',
            'required_findings_covered':not missing,'missing_terms':missing,'sensitive_output_rejected':not forbidden,
            'unexpected_citations':unexpected,'citations_valid':not unexpected,
            'abstention_correct':bool(actual.get('abstained'))==bool(case.get('expect_abstain',False))})
    groups={}
    for provenance in ['synthetic','real']:
        rows=[row for row in cases if row['provenance']==provenance]
        evaluated=[row for row in rows if row['status']=='evaluated']
        groups[provenance]={'case_count':len(rows),'evaluated_count':len(evaluated),'status':'evaluated' if evaluated else 'no_outputs',
            'findings_pass_count':sum(row['required_findings_covered'] for row in evaluated),
            'citation_pass_count':sum(row['citations_valid'] for row in evaluated),
            'sensitive_output_pass_count':sum(row['sensitive_output_rejected'] for row in evaluated),
            'abstention_pass_count':sum(row['abstention_correct'] for row in evaluated)}
    return {'groups':groups,'cases':cases,'output_provenance':outputs.get('provenance','unspecified'),
            'external_calls':0,'limitations':'Term/citation checks are regression indicators, not clinical or field diagnostic accuracy.'}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--dataset',type=Path,required=True);parser.add_argument('--outputs',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=evaluate(json.loads(args.dataset.read_text()),json.loads(args.outputs.read_text()));args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result['groups']))
if __name__=='__main__':main()
