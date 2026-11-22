"""A lease-expired run may finish filing; a stopped/refused/reassigned job may not.

Ownership and run identity are still checked by the normal completion endpoint.
This flag never authorises a new execution or customer quotation release.
"""


def may_recover(run):
    return (getattr(run,'status','')=='error' and bool(getattr(run,'lease_expired',False))
            and not bool(getattr(run,'cancel_requested',False))
            and not bool(getattr(run,'stopped_by_hand',False))
            and not bool(getattr(run,'instruction_refused',False)))
