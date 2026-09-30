"""Fixed neuron groups for recording nociceptive propagation. Recording only.

Groups are resolved once from MaleCNS v1.0 annotations. Their spike sums are
written to the audit; nothing here feeds the decoder or selects actions.
"""
import hashlib
import numpy as np

TOP_SNXX29_ASCENDING = ['AN09B018', 'AN05B004', 'AN17A018', 'ANXXX196', 'AN05B097']
# SNch01's strongest downstream partners by summed synapse weight (this graph, male-cns:v1.0). AN09B018,
# AN05B004 and ANXXX196 overlap with SNxx29's own top ascending partners; AN01A021 and ANXXX055 are specific
# to SNch01.
TOP_SNCH01_ASCENDING = ['AN01A021', 'ANXXX055']
LISTED_ID_LIMIT = 64


def activity_groups(annotations, stimulated=None):
    """Map group name -> node indices. ``annotations`` row i describes node i."""
    types = annotations['type'].fillna('').astype(str)
    superclass = annotations['superclass'].fillna('').astype(str)
    cls = annotations['class'].fillna('').astype(str)
    side = annotations['somaSide'].fillna(annotations['rootSide']).fillna('').astype(str)
    masks = {'SNxx29': types.eq('SNxx29'), 'SNch01': types.eq('SNch01')}
    masks.update({t: types.eq(t) for t in TOP_SNXX29_ASCENDING})
    masks.update({t: types.eq(t) for t in TOP_SNCH01_ASCENDING})
    masks.update({
        'ascending_neuron': superclass.eq('ascending_neuron'),
        'DAN': cls.eq('DAN'),
        'PPL1': types.str.startswith('PPL1'),
        'PPL101': types.eq('PPL101'),
        'PAM': types.str.startswith('PAM'),
        'MBON': types.str.startswith('MBON'),
        'KC': types.str.startswith('KC'),
        'descending_neuron': superclass.eq('descending_neuron'),
        'DNp20_L': types.eq('DNp20') & side.eq('L'),
        'DNp20_R': types.eq('DNp20') & side.eq('R'),
        'DNpe017': types.eq('DNpe017'),
    })
    groups = {k: np.flatnonzero(v.to_numpy()).astype(np.int32) for k, v in masks.items()}
    if stimulated is not None:
        groups = {'stimulated': np.asarray(stimulated, dtype=np.int32), **groups}
    return groups


class ActivityMonitor:
    def __init__(self, groups, ids):
        self.groups = {k: np.asarray(v, dtype=np.int32) for k, v in groups.items()}
        self.ids = np.asarray(ids)

    def sums(self, counts):
        return {k: int(counts[ix].sum()) for k, ix in self.groups.items()}

    def report(self):
        out = {}
        for k, ix in self.groups.items():
            body = self.ids[ix]
            entry = {'neurons': len(ix), 'body_ids_sha256': hashlib.sha256(body.astype(np.int64).tobytes()).hexdigest()}
            if len(ix) <= LISTED_ID_LIMIT:
                entry['body_ids'] = [str(b) for b in body]
            out[k] = entry
        return {'dataset': 'male-cns', 'dataset_version': 'v1.0', 'measure': 'spike count per game tic', 'groups': out}
