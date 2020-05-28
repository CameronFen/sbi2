from typing import Union, Tuple

import torch
from torch import Tensor
from torch.distributions import Distribution

from sbi.inference.posteriors.sbi_posterior import NeuralPosterior
from sbi.utils.metrics import c2st

from sbi.simulators.linear_gaussian import (
    get_true_posterior_log_prob_linear_gaussian_mvn_prior,
    get_true_posterior_log_prob_linear_gaussian_n_prior,
)


def dkl_via_monte_carlo(
    p: Union[NeuralPosterior, Distribution],
    q: Union[NeuralPosterior, Distribution],
    num_samples: int = 1000,
) -> Tensor:
    r"""
    Returns Monte-Carlo estimate of the Kullback-Leibler divergence of distributions p,
    q.

    Unlike torch.distributions.kl.kl_divergence(p, q), this function does not require p
    and q to be torch.Distribution objects, but just to provide sample() and log_prob()
    methods.

    For added flexibility, we squeeze the output of log_prob() and hence can handle
    outputs such as torch.tensor([[p_1], [p_2], [p_3]]), instead of just
    torch.tensor([p_1, p_2, p_3]) (like torch.distributions.kl.kl_divergence(p, q)),
    with p_n being probabilities.

    Computes $D = \int p(x) * log(p(x)/q(x)) dx \approx 1/N * log(p(x)/q(x))$
    Args:
        p, q: distribution-like objects with sample() and log_prob() methods
        num_samples: number of samples that the Monte-Carlo estimate is based on
    """

    cumulative_log_ratio = torch.tensor([0.0])
    for _ in range(num_samples):
        target_sample = p.sample()
        # squeeze to make the shapes match. The output from log_prob() is either
        # torch.tensor([[p_1], [p_2], [p_3]]) or torch.tensor([p_1, p_2, p_3]), so we
        # squeeze to make both of them torch.tensor([p_1, p_2, p_3])
        cumulative_log_ratio += torch.squeeze(
            p.log_prob(target_sample)
        ) - torch.squeeze(q.log_prob(target_sample))

    dkl = cumulative_log_ratio / num_samples

    return dkl


def get_dkl_gaussian_prior(
    posterior: NeuralPosterior, true_observation: Tensor, num_dim: int
) -> Tensor:
    """
    Return the Kullback-Leibler divergence between estimated posterior (with Gaussian
    prior) and ground-truth target posterior.

    Args:
        posterior: estimated posterior
        true_observation: observation where we evaluate the posterior
        num_dim: dimensionality of the problem
    """

    if num_dim == 1:
        target_dist = get_true_posterior_log_prob_linear_gaussian_n_prior(
            true_observation,
        )
    else:
        target_dist = get_true_posterior_log_prob_linear_gaussian_mvn_prior(
            true_observation,
        )

    return dkl_via_monte_carlo(target_dist, posterior, num_samples=200)


def get_prob_outside_uniform_prior(posterior: NeuralPosterior, num_dim: int) -> Tensor:
    """
    Return posterior probability for a parameter set outside of the prior support.

    Args:
        posterior: estimated posterior
        num_dim: dimensionality of the problem
    """
    # Test whether likelihood outside prior support is zero. Prior bounds are [-1, 1] in
    # each dimension, so tensor of 2s will be out of bounds.
    sample_outside_support = 2 * torch.ones(num_dim)

    return torch.exp(posterior.log_prob(sample_outside_support))


def get_normalization_uniform_prior(
    posterior: NeuralPosterior, prior: Distribution, true_observation: Tensor,
) -> Tuple[Tensor, Tensor, Tensor]:
    """
    Return the unnormalized posterior likelihood, the normalized posterior likelihood,
    and the estimated acceptance probability.

    Args:
        posterior: estimated posterior
        prior: prior distribution
        true_observation: observation where we evaluate the posterior
    """

    # Test normalization.
    prior_sample = prior.sample()

    # Compute unnormalized density, i.e. just the output of the density estimator.
    posterior_likelihood_unnorm = torch.exp(
        posterior.log_prob(prior_sample, norm_posterior_snpe=False)
    )
    # Compute the normalized density, scale up output of the density
    # estimator by the ratio of posterior samples within the prior bounds.
    posterior_likelihood_norm = torch.exp(
        posterior.log_prob(prior_sample, norm_posterior_snpe=True)
    )

    # Estimate acceptance ratio through rejection sampling.
    acceptance_prob = posterior.get_leakage_correction(x=true_observation)

    return posterior_likelihood_unnorm, posterior_likelihood_norm, acceptance_prob


def check_c2st(x: Tensor, y: Tensor, alg: str, tol: float = 0.1) -> None:
    """Compute classification based two-sample test accuracy and assert it close to
    chance."""

    score = c2st(x, y).item()

    print(f"c2st for {alg} is {score:.2f}.")

    assert (
        (0.5 - tol) <= score <= (0.5 + tol)
    ), f"c2st={score:.2f} is too far from the desired near-chance performance."