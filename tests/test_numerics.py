"""Separate field convergence from optional flux-error estimator controls."""
import pytest
from pcb_em.common import WorkflowError
from pcb_em.geometry import linear_settings


def test_estimator_settings_do_not_relax_field_solve():
    result = linear_settings({'numerics':{'estimator_tolerance':.01,'estimator_max_iterations':1000}}, estimator_multigrid=True)
    assert result == {'Tol':1e-8,'MaxIts':200,'EstimatorMG':True,
                      'EstimatorTol':.01,'EstimatorMaxIts':1000}


@pytest.mark.parametrize('options', [{'estimator_tolerance':0}, {'estimator_tolerance':1},
                                   {'estimator_tolerance':float('nan')}, {'estimator_max_iterations':0}])
def test_invalid_estimator_settings_are_rejected(options):
    with pytest.raises(WorkflowError):linear_settings({'numerics':options})
