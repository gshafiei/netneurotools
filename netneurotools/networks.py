# -*- coding: utf-8 -*-

import numpy as np
from sklearn.utils.validation import check_random_state


def func_correlation(data):
    """
    Computes group-averaged functional correlation matrix

    Parameters
    ----------
    data : (N, T, S) array_like
        Pre-processed functional time series, where `N` is nodes, `T` is
        time, and `S` is subjects

    Returns
    -------
    corr : (N, N) array
        GRoup average of subject-level functional correlations
    """

    corrs = [np.corrcoef(data[..., sub]) for sub in range(data.shape[-1])]

    # average correlations across all subjects
    return np.mean(corrs, axis=0)


def func_consensus(data, n_boot=1000, ci=95, seed=None):
    """
    Calculates group-level, thresholded functional connectivity matrix

    This function concatenates all time series in `data` and computes a group
    correlation matrix based on this extended time series. It then generates
    length `t` bootstrapped samples from the concatenated matrix and estimates
    confidence intervals for all correlations. Correlations whose sign is
    consistent across bootstraps are retained; inconsistent correlationsare set
    to zero.

    Parameters
    ----------
    data : (N, T, S) array_like
        Pre-processed functional time series of shape, where `N` is the number
        of nodes, `T` is the number of volumes in the time series, and `S` is
        the number of subjects
    n_boot : int, optional
        Number of bootstraps for which to generate correlation. Default: 1000
    ci : (0, 100) float, optional
        Confidence interval for assessing reliability of correlations with
        bootstraps. Default: 95
    seed : int, optional
        Random seed. Default: None

    Returns
    -------
    consensus : (N, N) numpy.ndarray
        Thresholded, group-level correlation matrix
    """

    rs = check_random_state(seed)

    if ci > 100 or ci < 0:
        raise ValueError("`ci` must be between 0 and 100.")

    collapsed_data = data.reshape((len(data), -1), order='F')
    consensus = np.corrcoef(collapsed_data)

    bootstrapped_corrmat = np.zeros((len(data), len(data), n_boot))

    # generate `n_boot` bootstrap correlation matrices by sampling `t` time
    # points from the concatenated time series
    for boot in range(n_boot):
        inds = rs.randint(collapsed_data.shape[-1], size=data.shape[1])
        bootstrapped_corrmat[:, :, boot] = np.corrcoef(collapsed_data[:, inds])

    # extract the CIs from the bootstrapped correlation matrices
    bootstrapped_ci = np.percentile(bootstrapped_corrmat, [100 - ci, ci],
                                    axis=-1)

    # remove unreliable (i.e., CI zero-crossing) correlations
    indices_to_keep = np.sign(bootstrapped_ci).sum(axis=0).astype(bool)
    consensus[~indices_to_keep] = 0

    return consensus


def ecdf(data):
    """
    Estimates empirical cumulative distribution function of `data`

    Taken directly from StackOverflow. See original answer at
    https://stackoverflow.com/questions/33345780.

    Parameters
    ----------
    data : array_like

    Returns
    -------
    prob : numpy.ndarray
        Cumulative probability
    quantiles : numpy.darray
        Quantiles
    """

    sample = np.atleast_1d(data)

    # find the unique values and their corresponding counts
    quantiles, counts = np.unique(sample, return_counts=True)

    # take the cumulative sum of the counts and divide by the sample size to
    # get the cumulative probabilities between 0 and 1
    prob = np.cumsum(counts).astype(float) / sample.size

    # match MATLAB
    prob, quantiles = np.append([0], prob), np.append(quantiles[0], quantiles)

    return prob, quantiles


def struct_consensus(data, distance, hemiid):
    """
    Calculates group-averaged structural connectivity matrix

    Takes as input a weighted stack of connectivity matrices with dimensions
    [n x n x subject] where n is the number of nodes and subject is the number
    of matrices in the stack. The matrices must be weighted, and ideally with
    continuous weights (e.g. fractional anisotropy rather than streamline
    count). The second input is a pairwise distance matrix (i.e. distance(i,j)
    is the Euclidean distance between nodes i and j). The final input is an
    [n x 1] vector which labels nodes as in the left (0) or right (1)
    hemisphere.

    This function estimates the average edge length distribution and builds
    a group-averaged connectivity matrix that approximates this
    distribution with density equal to the mean density across subjects.

    The algorithm works as follows:
    1. Estimate the cumulative edge length distribution,
    2. Divide the distribution into M length bins, one for each edge that
       will be added to the group-average matrix, and
    3. Within each bin, select the edge that is most consistently expressed
       expressed across subjects, breaking ties according to average edge
       weight (which is why the input matrix `data` must be weighted).

    The algorithm works separately on within/between hemisphere links.

    Parameters
    ----------
    data : (N, N, S) array_like
        Weighted connectivity matrices (i.e., fractional anisotropy), where `N`
        is nodes and `S` is subjects
    distance : (N, N) array_like
        Array where `distance[i, j]` is the Euclidean distance between nodes
        `i` and `j`
    hemiid : (N, 1) array_like
        Hemisphere ids for nodes (N) where right = 0 and left = 1

    Returns
    -------
    consensus : (N, N) numpy.ndarray
        Binary, group-level connectivity matrix
    """

    num_node, _, num_sub = data.shape      # info on connectivity matrices
    pos_data = data > 0                    # location of + values in matrix
    pos_data_count = pos_data.sum(axis=2)  # num sub with + values at each node

    with np.errstate(divide='ignore', invalid='ignore'):
        average_weights = data.sum(axis=2) / pos_data_count

    # empty array to hold inter/intra hemispheric connections
    consensus = np.zeros((num_node, num_node, 2))

    for conn_type in range(2):  # iterate through inter/intra hemisphere conn
        if conn_type == 0:      # get inter hemisphere edges
            inter_hemi = (hemiid == 0) @ (hemiid == 1).T
            keep_conn = np.logical_or(inter_hemi, inter_hemi.T)
        else:                   # get intra hemisphere edges
            right_hemi = (hemiid == 0) @ (hemiid == 0).T
            left_hemi = (hemiid == 1) @ (hemiid == 1).T
            keep_conn = np.logical_or(right_hemi @ right_hemi.T,
                                      left_hemi @ left_hemi.T)

        # mask the distance array for only those edges we want to examine
        full_dist_conn = distance * keep_conn
        upper_dist_conn = np.atleast_3d(np.triu(full_dist_conn))

        # generate array of weighted (by distance), positive edges across subs
        pos_dist = pos_data * upper_dist_conn
        pos_dist = pos_dist[np.nonzero(pos_dist)]

        # determine average # of positive edges across subs
        # we will use this to bin the edge weights
        avg_conn_num = len(pos_dist) / num_sub

        # estimate empirical CDF of weighted, positive edges across subs
        cumprob, quantiles = ecdf(pos_dist)
        cumprob = np.round(cumprob * avg_conn_num).astype(int)

        # empty array to hold group-average matrix for current connection type
        # (i.e., inter/intra hemispheric connections)
        group_conn_type = np.zeros((num_node, num_node))

        # iterate through bins (for edge weights)
        for n in range(1, int(avg_conn_num) + 1):
            # get current quantile of interest
            curr_quant = quantiles[np.logical_and(cumprob >= (n - 1),
                                                  cumprob < n)]

            # find edges in distance connectivity matrix w/i current quantile
            mask = np.logical_and(full_dist_conn >= curr_quant.min(),
                                  full_dist_conn <= curr_quant.max())
            i, j = np.where(np.triu(mask))  # indices of edges of interest

            c = pos_data_count[i, j]   # get num sub with + values at edges
            w = average_weights[i, j]  # get averaged weight of edges

            # find locations of edges most commonly represented across subs
            indmax = np.argwhere(c == c.max())

            # determine index of most frequent edge; break ties with higher
            # weighted edge
            if indmax.size == 1:  # only one edge found
                group_conn_type[i[indmax], j[indmax]] = 1
            else:                 # multiple edges found
                indmax = indmax[np.argmax(w[indmax])]
                group_conn_type[i[indmax], j[indmax]] = 1

        consensus[:, :, conn_type] = group_conn_type

    # collapse across hemispheric connections types and make symmetrical array
    consensus = consensus.sum(axis=2)
    consensus = np.logical_or(consensus, consensus.T).astype(int)

    return consensus