from math import exp

import numpy as np

from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import Matern

from scipy import stats
from scipy.optimize import OptimizeResult, fmin_l_bfgs_b

def _acquisition_func(x0, gp, prev_best, func, xi=0.01, kappa=1.96):
    x0 = np.asarray(x0)
    if x0.ndim == 1:
        x0 = np.expand_dims(x0, axis=0)

    predictions, std = gp.predict(x0, return_std=True)

    if func == 'UCB':
        acquisition_func = predictions - kappa * std
    elif func == 'EI':
        # When std is 0.0, Z is huge, safe to say the pdf at Z is 0.0
        # and cdf at Z is 1.0
        std_mask = std != 0.0
        acquisition_func = prev_best - predictions - xi
        Z = acquisition_func[std_mask] / std[std_mask]
        acquisition_func[std_mask] = std[std_mask] * (
            Z * stats.norm.cdf(Z) + stats.norm.pdf(Z))
    else:
        raise ValueError(
            'acquisition_function not implemented yet : '
            + func)

    if acquisition_func.shape == (1, 1):
        return acquisition_func[0]
    return acquisition_func


def gp_minimize(func, bounds=None, search="sampling", random_state=None,
                maxiter=1000, acq="UCB", num_points=500):
    """
    Black-box optimization using Gaussian Processes.

    If every function evaluation is expensive, for instance
    when the parameters are the hyperparameters of a neural network
    and the function evaluation is the mean cross-validation score across
    ten folds, optimizing the hyperparameters by standared optimization
    routines would take for ever!

    The idea is to approximate the function using a Gaussian process.
    In other words the function values are assumed to follow a multivariate
    gaussian. The covariance of the function values are given by a
    GP kernel between the parameters. Then a smart choice to choose the
    next parameter to evaluate can be made by the acquistion function
    over the Gaussian posterior which is much quicker to evaluate.

    Parameters
    ----------
    func: callable
        Function to minimize. Should take a array of parameters and
        return the function value.

    bounds: array-like, shape (n_parameters, 2)
        ``bounds[i][0]`` should give the lower bound of each parameter and
        ``bounds[i][1]`` should give the upper bound of each parameter.

    search: string, "sampling" or "lbfgs"
        Searching for the next possible candidate to update the Gaussian prior
        with.

        If search is set to "sampling", ``num_points`` are sampled randomly
        and the Gaussian Process prior is updated with that point that gives
        the best acquision value over the Gaussian posterior.

        If search is set to "lbfgs", then a point is sampled randomly, and
        lbfgs is run for 10 iterations optimizing the acquistion function
        over the Gaussian posterior.

    random_state: int, RandomState instance, or None (default)
        Set random state to something other than None for reproducible
        results.

    maxiter: int, default 1000
        Number of iterations to find the minimum. In other words, the
        number of function evaluations.

    acq: string, default "UCB"
        Function to minimize over the gaussian posterior. Can be either
        the "UCB" which refers to the UpperConfidenceBound or "EI" which
        is the Expected Improvement.

    num_points: int, default 500
        Number of points to sample to determine the next "best" point.
        Useless if search is set to "lbfgs".

    Returns
    -------
    res: OptimizeResult, scipy object
        The optimization result returned as a OptimizeResult object.
        Important attributes are
        ``x`` - float, the optimization solution,
        ``fun`` - float, the value of the function at the optimum,
        ``models``- gp_models[i]. the prior on the function fit at
                       iteration[i].
        ``func_vals`` - the function value at the ith iteration.
        ``x_iters`` - the value of ``x`` corresponding to the function value
                      at the ith iteration.
        For more details related to the OptimizeResult object, refer
        http://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.OptimizeResult.html
    """
    rng = np.random.RandomState(random_state)

    num_params = len(bounds)
    lower_bounds, upper_bounds = zip(*bounds)
    upper_bounds = np.asarray(upper_bounds)
    lower_bounds = np.asarray(lower_bounds)
    x0 = rng.rand(num_params)
    func_val = [func(lower_bounds + (upper_bounds - lower_bounds) * x0)]

    length_scale = np.ones(num_params)
    gp_params = {
        'kernel': Matern(length_scale=length_scale, nu=2.5),
        'normalize_y': True,
        'random_state': random_state
    }
    lbfgs_bounds = np.tile((0, 1), (num_params, 1))

    gp_models = []
    x = np.reshape(x0, (1, -1))

    for i in range(maxiter):
        gpr = GaussianProcessRegressor(**gp_params)
        gpr.fit(x, func_val)

        if search == "sampling":
            sampling = rng.rand(num_points, num_params)
            acquis = _acquisition_func(sampling, gpr, np.min(func_val), acq)
            best_arg = np.argmin(acquis)
            best_x = sampling[best_arg]
        elif search == "lbfgs":
            init = rng.rand(num_params)
            best_x, _, _ = fmin_l_bfgs_b(
                _acquisition_func,
                np.asfortranarray(init),
                args=(gpr, np.min(func_val), acq),
                bounds=lbfgs_bounds, approx_grad=True, maxiter=10)

        gp_models.append(gpr)

        best_f = func(lower_bounds + (upper_bounds - lower_bounds) * best_x)
        x_list = x.tolist()
        x_list.append(best_x)
        x = np.asarray(x_list)
        func_val.append(best_f)

    x = lower_bounds + (upper_bounds - lower_bounds) * x
    func_ind = np.argmin(func_val)
    x_val = x[func_ind]
    best_func_val = func_val[func_ind]
    res = OptimizeResult()
    res.models = gp_models

    res.x = x_val
    res.fun = best_func_val
    res.func_vals = func_val
    res.x_iters = x

    return res