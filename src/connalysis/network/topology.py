# Network analysis functions based on topological constructions
#
# Author(s): D. Egas Santander, M. Santoro, J. Smith, V. Sood
# Last modified: 03/2023

#TODO: rc_in_simplex, filtered_simplex_counts, persistence


#######################################################
################# UNWEIGHTED NETWORKS #################
#######################################################

import resource
import numpy as np
import pandas as pd
import logging
import scipy.sparse as sp

#Imports not used as global imports, check what can be removed.
import sys
import tempfile
import pickle
from functools import partial
from pathlib import Path
from tqdm import tqdm
from typing import List




LOG = logging.getLogger("connectome-analysis-topology")
LOG.setLevel("INFO")
logging.basicConfig(format="%(asctime)s %(levelname)-8s %(message)s",
                    level=logging.INFO,
                    datefmt="%Y-%m-%d %H:%M:%S")



def rc_submatrix(adj):
    """Returns the symmetric submatrix of reciprocal connections of adj
    Parameters
    ----------
    adj : 2d array or sparse matrix
        Adjacency matrix of the directed network.  A non-zero entry adj[i,j] implies there is an edge from i to j.

    Returns
    -------
    sparse matrix
        symmetric matrix of the same dtype as adj of reciprocal connections
    """
    adj=sp.csr_matrix(adj)
    if np.count_nonzero(adj.diagonal()) != 0:
        logging.warning('The diagonal is non-zero and this may lead to errors!')
    mask=adj.copy().astype('bool')
    mask=(mask.multiply(mask.T))
    mask.eliminate_zeros
    return adj.multiply(mask).astype(adj.dtype)

def underlying_undirected_matrix(adj):
    """Returns the symmetric matrix of undirected connections of adj
    Parameters
    ----------
    adj : 2d array or sparse matrix
        Adjacency matrix of the directed network.  A non-zero entry adj[i,j] implies there is an edge from i to j.

    Returns
    -------
    sparse boolean matrix
        Corresponding to the symmetric underlying undirected graph
    """
    adj=sp.csr_matrix(adj)
    if np.count_nonzero(adj.diagonal()) != 0:
        logging.warning('The diagonal is non-zero and this may lead to errors!')
    return (adj+adj.T).astype('bool')


def _series_by_dim(from_array, name_index=None, index=None, name=None):
    """A series of counts, like simplex counts:
    one count for a given value of simplex dimension.
    """
    if from_array is None:
        return None
    if index is None:
        index = pd.Index(range(len(from_array)), name=name_index)
    else:
        assert len(index)==len(from_array), "array and index are not the same length"
        index = pd.Index(index, name=name_index)
    return pd.Series(from_array, index=index, name=name)


def _frame_by_dim(from_array, no_columns, name, index):
    """A dataframe of counts, like node participation:
    one count for a node and simplex dimension.
    """
    if from_array is None:
        return None
    #Todo add method for when no_columns is not given
    columns = pd.Index(range(no_columns), name=index)
    return pd.DataFrame(from_array, columns=columns).fillna(0).astype(int)


QUANTITIES = {"simplices",
              "node-participation",
              "bettis",
              "bidrectional-edges"}

def _flagser_counts(adjacency,
                    max_simplices=False,
                    count_node_participation=False,
                    list_simplices=False,
                    threads=1,max_dim=-1):
    """Call package `pyflagsercount's flagser_count` method that can be used to compute
    some analyses, getting counts of quantities such as simplices,
    or node-participation (a.k.a. `containment`)
    """
    import pyflagsercount
    adjacency = sp.csr_matrix(adjacency.astype(bool).astype(int))
    if np.count_nonzero(adjacency.diagonal()) != 0:
        logging.warning('The diagonal is non-zero!  Non-zero entries in the diagonal will be ignored.')


    flagser_counts = pyflagsercount.flagser_count(adjacency,
                                                  max_simplices=max_simplices,
                                                  containment=count_node_participation,
                                                  return_simplices=list_simplices,
                                                  threads=threads,max_dim=max_dim)

    counts =  {"euler": flagser_counts.pop("euler"),
               "simplex_counts": _series_by_dim(flagser_counts.pop("cell_counts"),
                                                name="simplex_count", name_index="dim"),
               "max_simplex_counts": _series_by_dim(flagser_counts.pop("max_cell_counts", None),
                                                    name="max_simplex_count", name_index="dim"),
               "simplices": flagser_counts.pop("simplices", None)}
    if counts["max_simplex_counts"] is None:
        max_dim_participation=counts["simplex_counts"].shape[0]
    else:
        max_dim_participation=counts["max_simplex_counts"].shape[0]
    counts["node_participation"]= _frame_by_dim(flagser_counts.pop("contain_counts", None),max_dim_participation,
                                                name="node_participation", index="node")
    counts.update(flagser_counts)
    return counts


def node_degree(adj, node_properties=None, direction=None, weighted=False, **kwargs):
    """Compute degree of nodes in network adj
    Parameters
    ----------
    adj : 2d array or sparse matrix
        Adjacency matrix of the directed network.  A non-zero entry adj[i,j] implies there is an edge from i to j
        of weight adj[i,j].
    node_properties : data frame
        Data frame of neuron properties in adj. Only necessary if used in conjunction with TAP or connectome utilities.
    direction : string or tuple of strings
        Direction for which to compute the degree

        'IN' - In degree

        'OUT'- Out degree

        None or ('IN', 'OUT') - Total degree i.e. IN+OUT

    Returns
    -------
    series or data frame

    Raises
    ------
    Warning
        If adj has non-zero entries in the diagonal
    AssertionError
        If direction is invalid
    """
    assert not direction or direction in ("IN", "OUT") or tuple(direction) == ("IN", "OUT"),\
        f"Invalid `direction`: {direction}"

    if not isinstance(adj, np. ndarray):
        matrix = adj.toarray()
    else:
        matrix=adj.copy()
    if not weighted:
        matrix=matrix.astype('bool')
    if np.count_nonzero(np.diag(matrix)) != 0:
        logging.warning('The diagonal is non-zero!  This may cause errors in the analysis')
    index = pd.Series(range(matrix.shape[0]), name="node")
    series = lambda array: pd.Series(array, index)
    in_degree = lambda: series(matrix.sum(axis=0))
    out_degree = lambda: series(matrix.sum(axis=1))

    if not direction:
        return in_degree() + out_degree()

    if tuple(direction) == ("IN", "OUT"):
        return pd.DataFrame({"IN": in_degree(), "OUT": out_degree()})

    if tuple(direction) == ("OUT", "IN"):
        return pd.DataFrame({"OUT": out_degree(), "IN": in_degree()})

    return in_degree() if direction == "IN" else out_degree()

def node_k_degree(adj, node_properties=None, direction=("IN", "OUT"), max_dim=-1, **kwargs):
    #TODO: Generalize from one population to another
    """Compute generalized degree of nodes in network adj.  The k-(in/out)-degree of a node v is the number of
    k-simplices with all its nodes mapping to/from the node v.
    Parameters
    ----------
    adj : 2d array or sparse matrix
        Adjacency matrix of the directed network.  A non-zero entry adj[i,j] implies there is an edge from i to j
        of weight adj[i,j].  The matrix can be asymmetric, but must have 0 in the diagonal.
    node_properties : dataframe
        Data frame of neuron properties in adj.  Only necessary if used in conjunction with TAP or connectome utilities.
    direction : string
        Direction for which to compute the degree

        'IN' - In degree

        'OUT'- Out degree

        (’IN’, ’OUT’) - both
    max_dim : int
        Maximal dimension for which to compute the degree max_dim >=2 or -1 in
        which case it computes all dimensions.

    Returns
    -------
    data frame
        Table of of k-(in/out)-degrees

    Raises
    ------
    Warning
        If adj has non-zero entries in the diagonal which are ignored in the analysis
    AssertionError
        If direction is invalid
    AssertionError
        If not max_dim >1

    Notes
    -----
    Note that the k-in-degree of a node v is the number of (k+1) simplices the node v is a sink of.
    Dually, the k-out-degree of a node v is the number of (k+1) simplices the node v is a source of.
    """
    matrix = sp.csr_matrix(adj)
    assert (max_dim > 1) or (max_dim==-1), "max_dim should be >=2"
    assert direction in ("IN", "OUT") or tuple(direction) == ("IN", "OUT"), \
        f"Invalid `direction`: {direction}"
    if np.count_nonzero(matrix.diagonal()) != 0:
        logging.warning('The diagonal is non-zero!  Non-zero entries in the diagonal will be ignored.')
    import pyflagsercount
    flagser_out = pyflagsercount.flagser_count(matrix, return_simplices=True, max_dim=max_dim)
    max_dim_possible = len(flagser_out['cell_counts']) - 1
    if max_dim==-1:
        max_dim = max_dim_possible
    elif max_dim > max_dim_possible:
        logging.warning("The maximum dimension selected is not attained")
        max_dim = max_dim_possible
    if (max_dim <= 1) and (max_dim!=-1):
        print("There are no simplices of dimension 2 or higher")
    else:
        index = pd.Series(range(matrix.shape[0]), name="node")
        generalized_degree = pd.DataFrame(index=index)
        for dim in np.arange(2, max_dim + 1):
            if "OUT" in direction:
                # getting source participation across dimensions
                x, y = np.unique(np.array(flagser_out['simplices'][dim])[:, 0], return_counts=True)
                generalized_degree[f'{dim}_out_degree'] = pd.Series(y, index=x)
            if "IN" in direction:
                # getting sink participation across dimensions
                x, y = np.unique(np.array(flagser_out['simplices'][dim])[:, dim], return_counts=True)
                generalized_degree[f'{dim}_in_degree'] = pd.Series(y, index=x)
        return generalized_degree.fillna(0)


def simplex_counts(adj, node_properties=None,max_simplices=False,
                   threads=1,max_dim=-1, simplex_type='directed', **kwargs):
    """Compute the number of simplex motifs in the network adj.
    Parameters
    ----------
    adj : 2d array or sparse matrix
        Adjacency matrix of the directed network.  A non-zero entry adj[i,j] implies there is an edge from i to j
        of weight adj[i,j].  The matrix can be asymmetric, but must have 0 in the diagonal.
    node_properties : dataframe
        Data frame of neuron properties in adj.  Only necessary if used in conjunction with TAP or connectome utilities.
    max_simplices : bool
        If False counts all simplices in adj.
        If True counts only maximal simplices i.e., simplex motifs that are not contained in higher dimensional ones.
    max_dim : int
        Maximal dimension up to which simplex motifs are counted.
        The default max_dim = -1 counts all existing dimensions.  Particularly useful for large or dense graphs.
    simplex_type: string
        Type of simplex to consider (See Notes):

        ’directed’ - directed simplices

        ’undirected’ - simplices in the underlying undirected graph

        ’reciprocal’ - simplices in the undirected graph of reciprocal connections

    Returns
    -------
    series
        simplex counts

    Raises
    ------
    AssertionError
        If adj has non-zero entries in the diagonal which can produce errors.
    AssertionError
        If adj is not square.

    Notes
    -----
    A directed simplex of dimension k in adj is a set of (k+1) nodes which are all to all connected in a feedforward manner.
    That is, they can be ordered from 0 to k such that there is an edge from i to j whenever i < j.

    An undirected simplex of dimension k in adj is a set of (k+1) nodes in adj which are all to all connected.  That is, they
    are all to all connected in the underlying undirected graph of adj.  In the literature this is also called a (k+1)-clique
    of the underlying undirected graph.

    A reciprocal simplex of dimension k in adj is a set of (k+1) nodes in adj which are all to all reciprocally connected.
    That is, they are all to all connected in the undirected graph of reciprocal connections of adj.  In the literature this is
    also called a (k+1)-clique of the undirected graph of reciprocal connections.
    """
    adj=sp.csr_matrix(adj)
    assert np.count_nonzero(adj.diagonal()) == 0, 'The diagonal of the matrix is non-zero and this may lead to errors!'
    N, M = adj.shape
    assert N == M, 'Dimension mismatch. The matrix must be square.'


    #Symmetrize matrix if simplex_type is not 'directed'
    if simplex_type=='undirected':
        adj=sp.triu(underlying_undirected_matrix(adj)) #symmtrize and keep upper triangular only
    elif simplex_type=="reciprocal":
        adj=sp.triu(rc_submatrix(adj)) #symmtrize and keep upper triangular only

    flagser_counts = _flagser_counts(adj, threads=threads, max_simplices=max_simplices, max_dim=max_dim)
    if max_simplices:
        return flagser_counts["max_simplex_counts"]
    else:
        return flagser_counts["simplex_counts"]

def normalized_simplex_counts(adj, node_properties=None,
                   max_simplices=False, threads=1,max_dim=-1,
                   **kwargs):
    """Compute the ratio of directed/undirected simplex counts normalized to be between 0 and 1.
    See simplex_counts and undirected_simplex_counts for details.
    Parameters
    ----------
    adj : 2d array or sparse matrix
        Adjacency matrix of the directed network.  A non-zero entry adj[i,j] implies there is an edge from i to j
        of weight adj[i,j].  The matrix can be asymmetric, but must have 0 in the diagonal.
    node_properties : dataframe
        Data frame of neuron properties in adj.  Only necessary if used in conjunction with TAP or connectome utilities.
    max_simplices : bool
        If False counts all simplices in adj.
        If True counts only maximal simplices i.e., simplex motifs that are not contained in higher dimensional ones.
    max_dim : int
        Maximal dimension up to which simplex motifs are counted.
        The default max_dim = -1 counts all existing dimensions.  Particularly useful for large or dense graphs.

    Returns
    -------
    panda series
        Normalized simplex counts

    Raises
    ------
    AssertionError
        If adj has non-zero entries in the diagonal which can produce errors.

    Notes
    -----
    Maybe we should say why we choose this metric"""

    from scipy.special import factorial
    denominator=simplex_counts(adj, node_properties=node_properties,max_simplices=max_simplices,
                                          threads=threads,max_dim=max_dim,simplex_type='undirected', **kwargs).to_numpy()
    #Global maximum dimension since every directed simplex has an underlying undirected one of the same dimension
    max_dim_global=denominator.size
    #Maximum number of possible directed simplices for each undirected simplex across dimensions
    max_possible_directed=np.array([factorial(i+1) for i in np.arange(max_dim_global)])
    denominator=np.multiply(denominator, max_possible_directed)
    numerator=simplex_counts(adj, node_properties=node_properties,max_simplices=max_simplices,
                             threads=threads,max_dim=max_dim,simple_type='directed', **kwargs).to_numpy()
    numerator=np.pad(numerator, (0, max_dim_global-len(numerator)), 'constant', constant_values=0)
    return _series_by_dim(np.divide(numerator,denominator)[1:],name="normalized_simplex_counts",
                          index=np.arange(1,max_dim_global), name_index="dim")


def node_participation(adj, node_properties=None, max_simplices=False,
                       threads=1,max_dim=-1,simplex_type='directed',**kwargs):
    """Compute the number of simplex motifs in the network adj each node is part of.
    See simplex_counts for details.
    Parameters
    ----------
    adj : 2d array or sparse matrix
        Adjacency matrix of the directed network.  A non-zero entry adj[i,j] implies there is an edge from i to j.
        The matrix can be asymmetric, but must have 0 in the diagonal.
    node_properties : dataframe
        Data frame of neuron properties in adj.  Only necessary if used in conjunction with TAP or connectome utilities.
    max_simplices : bool
        If False (default) counts all simplices in adj.
        If True counts only maximal simplices i.e., simplex motifs that are not contained in higher dimensional ones.
    max_dim : int
        Maximal dimension up to which simplex motifs are counted.
        The default max_dim = -1 counts all existing dimensions.  Particularly useful for large or dense graphs.
    simplex_type : string
        Type of simplex to consider:

        ’directed’ - directed simplices

        ’undirected’ - simplices in the underlying undirected graph

        ’reciprocal’ - simplices in the undirected graph of reciprocal connections

    Returns
    -------
    data frame
        Indexed by the nodes in adj and with columns de dimension for which node participation is counted

    Raises
    -------
    AssertionError
        If adj has non-zero entries in the diagonal which can produce errors.
    AssertionError
        If adj is not square.
    """

    adj=sp.csr_matrix(adj).astype('bool')
    assert np.count_nonzero(adj.diagonal()) == 0, 'The diagonal of the matrix is non-zero and this may lead to errors!'
    N, M = adj.shape
    assert N == M, 'Dimension mismatch. The matrix must be square.'


    #Symmetrize matrix if simplex_type is not 'directed'
    if simplex_type=='undirected':
        adj=sp.triu(underlying_undirected_matrix(adj)) #symmtrize and keep upper triangular only
    elif simplex_type=="reciprocal":
        adj=sp.triu(rc_submatrix(adj)) #symmtrize and keep upper triangular only

    flagser_counts = _flagser_counts(adj, count_node_participation=True, threads=threads,
                                     max_simplices=max_simplices, max_dim=max_dim)
    return flagser_counts["node_participation"]

def list_simplices_by_dimension(adj, node_properties=None, max_simplices=False,max_dim=-1,nodes=None,
                                verbose=False, simplex_type='directed', **kwargs):
    """List all simplex motifs in the network adj.
    Parameters
    ----------
    adj : 2d (N,N)-array or sparse matrix
        Adjacency matrix of the directed network.  A non-zero entry adj[i,j] implies there is an edge from i to j.
        The matrix can be asymmetric, but must have 0 in the diagonal.
    node_properties :  data frame
        Data frame of neuron properties in adj.  Only necessary if used in conjunction with TAP or connectome utilities.
    max_simplices : bool
        If False (default) counts all simplices in adj.
        If True counts only maximal simplices i.e., simplex motifs that are not contained in higher dimensional ones.
    max_dim : int
        Maximal dimension up to which simplex motifs are counted.
        The default max_dim = -1 counts all existing dimensions.  Particularly useful for large or dense graphs.
    simplex_type : string
        Type of simplex to consider:

        ’directed’ - directed simplices

        ’undirected’ - simplices in the underlying undirected graph

        ’reciprocal’ - simplices in the undirected graph of reciprocal connections
    nodes : 1d array or None(default)
        Restrict to list only the simplices whose source node is in nodes.  If None list all simplices

    Returns
    -------
    series
        Simplex lists indexed per dimension.  The dimension k entry is a (no. of k-simplices, k+1)-array
        is given, where each row denotes a simplex.

    Raises
    ------
    AssertionError
        If adj has non-zero entries in the diagonal which can produce errors.
    AssertionError
        If adj is not square.
    AssertionError
        If nodes is not a subarray of np.arange(N)

    See Also
    --------
    simplex_counts : A function that counts the simplices instead of listing them and has descriptions of the
    simplex types.
    """
    LOG.info("COMPUTE list of %ssimplices by dimension", "max-" if max_simplices else "")

    import pyflagsercount

    adj=sp.csr_matrix(adj)
    assert np.count_nonzero(adj.diagonal()) == 0, 'The diagonal of the matrix is non-zero and this may lead to errors!'
    N, M = adj.shape
    assert N == M, 'Dimension mismatch. The matrix must be square.'
    if not nodes is None:
        assert np.isin(nodes,np.arange(N)).all(), "nodes must be a subarray of the nodes of the matrix"

    #Symmetrize matrix if simplex_type is not 'directed'
    if simplex_type=='undirected':
        adj=sp.triu(underlying_undirected_matrix(adj)) #symmtrize and keep upper triangular only
    elif simplex_type=="reciprocal":
        adj=sp.triu(rc_submatrix(adj)) #symmtrize and keep upper triangular only

    n_threads = kwargs.get("threads", kwargs.get("n_threads", 1))


    # Only the simplices that have sources stored in this temporary file will be considered
    if not nodes is None:
        import tempfile
        import os
        tmp_file = tempfile.NamedTemporaryFile(delete=False)
        vertices_todo = tmp_file.name + ".npy"
        np.save(vertices_todo, nodes, allow_pickle=False)
    else:
        vertices_todo=''

    #Generate simplex_list
    original=pyflagsercount.flagser_count(adj, max_simplices=max_simplices,threads=n_threads,max_dim=max_dim,
                                      vertices_todo=vertices_todo, return_simplices=True)['simplices']

    #Remove temporary file
    if not nodes is None:
        os.remove(vertices_todo)

    #Format output
    max_dim = len(original)
    dims = pd.Index(np.arange(max_dim), name="dim")
    simplices = pd.Series(original, name="simplices", index=dims).apply(np.array)
    #When counting all simplices flagser doesn't list dim 0 and 1 because they correspond to vertices and edges
    if not max_simplices:
        if nodes is None:
            nodes=np.arange(0, N)
        coom = adj.tocoo()
        simplices[0] = np.reshape(nodes, (nodes.size, 1))
        mask=np.isin(coom.row,nodes)
        simplices[1] = np.stack([coom.row[mask], coom.col[mask]]).T
    return simplices


'''
OLD VERSION KEEP HERE JUST FOR A LITTLE BIT FOR VISHAL'S CHECK 
def list_simplices_by_dimension(adj, nodes=None, max_simplices=False,
                                verbose=False, **kwargs):
    """List all the simplices (upto a max dimension) in an adjacency matrix.
    """
    LOG.info("COMPUTE list of %s simplices by dimension", "max-" if max_simplices else "")

    N, M = adj.shape
    assert N == M, f"{N} != {M}"

    n_threads = kwargs.get("threads", kwargs.get("n_threads", 1))
    fcounts = _flagser_counts(adj, list_simplices=True, max_simplices=max_simplices,
                              threads=n_threads)
    original = fcounts["simplices"]
    coom = adj.tocoo()

    max_dim = len(original)
    dims = pd.Index(np.arange(max_dim), name="dim")
    simplices = pd.Series(original, name="simplices", index=dims)
    simplices[0] = np.reshape(np.arange(0, N), (N, 1))
    simplices[1] = np.stack([coom.row, coom.col]).T
    return simplices'''

def cross_col_k_in_degree(adj_cross, adj_source, node_properties=None, max_simplices=False,
                          simplex_type='directed',threads=1,max_dim=-1,**kwargs):
    #TODO DO THE OUTDEGREE VERSION maybe one where populations are defined within a matrix?
    """Compute generalized in-degree of nodes in adj_target from nodes in adj_source.
    The k-in-degree of a node v is the number of k-simplices in adj_source with all its nodes mapping to v
    through edges in adj_cross.
    Parameters
    ----------
    adj_source : (n, n)-array or sparse matrix
        Adjacency matrix of the source network where n is the number of nodes in the source network.
        A non-zero entry adj_source[i,j] implies there is an edge from node i to j.
        The matrix can be asymmetric, but must have 0 in the diagonal.
    adj_cross : (n,m) array or sparse matrix
        Matrix of connections from the nodes in adj_n to the target population.
        n is the number of nodes in adj_source and m is the number of nodes in adj_target.
        A non-zero entry adj_cross[i,j] implies there is an edge from i-th node of adj_source
        to the j-th node of adj_target.
    node_properties : tuple of data frames
        Only necessary if used in conjunction with TAP or connectome utilities.
        Tuple (nrn_table_source, nrn_table_target)
        Each nrn_table is a data frame of neuron properties the neurons in adj_source, adj_target.
    max_simplices : bool
        If False counts all simplices.
        If True counts only maximal simplices.
    max_dim : int
        Maximal dimension up to which simplex motifs are counted.
        The default max_dim = -1 counts all existing dimensions.
        Particularly useful for large or dense graphs.

    Returns
    -------
    Data frame
        Table of cross-k-in-degrees indexed by the nodes in adj_target.

    Raises
    ------
    AssertionError
        If adj_source has non-zero entries in the diagonal which can produce errors.

    Notes
    -----
    We should probably write some notes here
    """
    adj_source=sp.csr_matrix(adj_source).astype('bool')
    adj_cross=sp.csr_matrix(adj_cross).astype('bool')
    assert np.count_nonzero(adj_source.diagonal()) == 0, \
    'The diagonal of the source matrix is non-zero and this may lead to errors!'
    assert adj_source.shape[0] == adj_source.shape[1], \
    'Dimension mismatch. The source matrix must be square.'
    assert adj_source.shape[0] == adj_cross.shape[0], \
    'Dimension mismatch. The source matrix and cross matrix must have the same number of rows.'

    n_source=adj_source.shape[0] #Size of the source population
    n_target=adj_cross.shape[1] #Size of the target population
    #Building a square matrix [[adj_source, adj_cross], [0,0]]
    adj=sp.bmat([[adj_source, adj_cross],
                 [sp.csr_matrix((n_target, n_source), dtype='bool'),
                  sp.csr_matrix((n_target, n_target), dtype='bool')]])
    #Tranposing to restric computation to ``source nodes'' in adj_target in flagsercount
    adj=adj.T
    nodes=np.arange(n_source, n_source+n_target) #nodes on target population
    slist=list_simplices_by_dimension(adj, max_simplices=max_simplices, max_dim=max_dim,nodes=nodes,
                                      simplex_type='directed',verbose=False,**kwargs)

    #Count participation as a source in transposed matrix i.e. participation as sink in the original
    cross_col_deg=pd.DataFrame(columns=slist.index[1:], index=nodes)
    for dim in slist.index[1:]:
        index,deg=np.unique(slist[dim][:,0],return_counts=True)
        cross_col_deg[dim].loc[index]=deg
    cross_col_deg=cross_col_deg.fillna(0)
    return cross_col_deg


def betti_counts(adj, node_properties=None,
                 min_dim=0, max_dim=[], simplex_type='directed', approximation=None,
                 **kwargs):
    """Count betti counts of flag complex of adj.  Type of flag complex is given by simplex_type.

    Parameters
    ----------
    adj : 2d (N,N)-array or sparse matrix
        Adjacency matrix of a directed network.  A non-zero entry adj[i,j] implies there is an edge from i to j.
        The matrix can be asymmetric, but must have 0 in the diagonal.  Matrix will be cast to 0,1 entries so weights
        will be ignored.
    node_properties :  data frame
        Data frame of neuron properties in adj.  Only necessary if used in conjunction with TAP or connectome utilities.
    min_dim : int
        Minimal dimension from which betti counts are computed.
        The default min_dim = 0 (counting number of connected components).
    max_dim : int
        Maximal dimension up to which simplex motifs are counted.
        The default max_dim = [] counts betti numbers up to the maximal dimension of the complex.
    simplex_type : string
        Type of flag complex to consider, given by the type of simplices it is built on.
        Possible types are:

        ’directed’ - directed simplices (directed flag complex)

        ’undirected’ - simplices in the underlying undirected graph (clique complex of the underlying undirected graph)

        ’reciprocal’ - simplices in the undirected graph of reciprocal connections (clique complex of the
        undirected graph of reciprocal connections.)
    approximation : list of integers  or None
        Approximation parameter for the computation of the betti numbers.  Useful for large networks.
        If None all betti numbers are computed exactly.
        Otherwise, min_dim must be 0 and approximation but be a list of positive integers or -1.
        The list approximation is either extended by -1 entries on the right or sliced from [0:max_dim+1] to obtain
        a list of length max_dim.  Each entry of the list denotes the approximation value for the betti computation
        of that dimension if -1 approximation in that dimension is set to None.

        If the approximation value at a given dimension is `a` flagser skips cells creating columns in the reduction
        matrix with more than `a` entries.  This is useful for hard problems.  For large, sparse networks a good value
        if often `100,00`.  If set to `1` that dimension will be virtually ignored.  See [1]_

    Returns
    -------
    series
        Betti counts indexed per dimension from min_dim to max_dim.

    Raises
    ------
    AssertionError
        If adj has non-zero entries in the diagonal which can produce errors.
    AssertionError
        If adj is not square.
    AssertionError
        If approximation != None and min_dim != 0.

    See Also
    --------
    [simplex_counts](network.md#src.connalysis.network.topology.simplex_counts) :
    A function that counts the simplices forming the complex from which bettis are count.
    Simplex types are described there in detail.

    Notes
    -----
    Let
    $$
    X(e^{j\omega } ) = x(n)e^{ - j\omega n}
    $$

    References
    ----------
    For details about the approximation algorithm see

    ..[1] D. Luetgehetmann, "Documentation of the C++ flagser library";
           [GitHub: luetge/flagser](https://github.com/luetge/flagser/blob/\
           master/docs/documentation_flagser.pdf).

    """
    LOG.info("Compute betti counts for %s-type adjacency matrix and %s-type node properties",
             type(adj), type(node_properties))

    from pyflagser import flagser_unweighted

    #Checking matrix
    adj = sp.csr_matrix(adj).astype(bool).astype('int')
    assert np.count_nonzero(adj.diagonal()) == 0, 'The diagonal of the matrix is non-zero and this may lead to errors!'
    N, M = adj.shape
    assert N == M, 'Dimension mismatch. The matrix must be square.'
    assert (not approximation in None) and (min_dim!=0), \
        'For approximation != None, min_dim must be set to 0.  \nLower dimensions can be ignored by setting approximation to 1 on those dimensions'

    # Symmetrize matrix if simplex_type is not 'directed'
    if simplex_type == 'undirected':
        adj = sp.triu(underlying_undirected_matrix(adj))  # symmtrize and keep upper triangular only
    elif simplex_type == "reciprocal":
        adj = sp.triu(rc_submatrix(adj))  # symmtrize and keep upper triangular only
    #Computing bettis
    if max_dim==[]:
        max_dim=np.inf

    if approximation==None:
        LOG.info("Run without approximation")
        bettis = flagser_unweighted(adj, min_dimension=min_dim, max_dimension=max_dim,
                                    directed=True, coeff=2,
                                    approximation=None)['betti']
    else:
        assert (all([isinstance(item,int) for item in approximation])) # assert it's a list of integers
        approximation=np.array(approximation)
        bettis=[]

        #Make approximation vector to be of size max_dim
        if max_dim!=np.inf:
            if approximation.size-1 < max_dim:#Vector too short so pad with -1's
                approximation=np.pad(approximation,
                                     (0,max_dim-(approximation.size-1)),
                                     'constant',constant_values=-1)
            if approximation.size-1>max_dim:#Vector too long, select relevant slice
                approximation=approximation[0:max_dim+1]
            #Sanity check
            LOG.info("Correct dimensions for approximation: %s", approximation.size==max_dim+1)

        #Split approximation into sub-vectors of same value to speed up computation
        diff=approximation[1:]-approximation[:-1]
        slice_indx=np.array(np.where(diff!=0)[0])+1

        #Compute betti counts
        for dims_range in  np.split(np.arange(approximation.size),slice_indx):
            n=dims_range[0] #min dim for computation
            N=dims_range[-1] #max dim for computation
            a=approximation[n]
            if a==-1:
                a=None
            LOG.info("Run betti for dim range %s-%s with approximation %s", n,N,a)
            bettis=bettis+flagser_unweighted(adj, min_dimension=n, max_dimension=N,
                                             directed=True, coeff=2,
                                             approximation=a)['betti']

        if max_dim==np.inf:
            n=approximation.size #min dim for computation
            N=np.inf #max dim for computation
            a=None
            LOG.info("Run betti for dim range %s-%s with approximation %s",n,N,a)
            bettis=bettis+flagser_unweighted(adj, min_dimension=n, max_dimension=N,
                                             directed=True, coeff=2,
                                             approximation=a)['betti']

    return pd.Series(bettis, name="betti_count",
                     index=pd.Index(np.arange(min_dim, len(bettis)-min_dim), name="dim"))


#################################################################################################################################################
#################################################################################################################################################
#################################################################################################################################################
#################################################################################################################################################  BELOW STILL TO CLEAN UP


def _binary2simplex(address, test=None, verbosity=1000000):
    """...Not used --- keeping it here as it is of interest to understanmd
    how simplices are represented on the disc by Flagser.
    #INPUT: Address of binary file storing simplices
    #OUTPUT: A list if lists L where L[i] contains the vertex ids of the i'th simplex,
    #          note the simplices appear in no particular order

    """
    LOG.info("Load binary simplex info from %s", address)
    simplex_info = pd.Series(np.fromfile(address, dtype=np.uint64))
    LOG.info("Done loading binary simplex info.")

    if test:
        simplex_info = simplex_info.iloc[0:test]

    mask64 = np.uint(1) << np.uint(63)
    mask21 = np.uint64(1 << 21) - np.uint64(1)
    mask42 = (np.uint64(1 << 42) - np.uint64(1)) ^ mask21
    mask63 = ((np.uint64(1 << 63) - np.uint64(1)) ^ mask42) ^ mask21
    end = np.uint64(2 ** 21 - 1)

    def decode_vertices(integer):
        decode_vertices.ncalls += 1
        if decode_vertices.ncalls % verbosity == 0:
            mem_used = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            LOG.info("\t progress %s / %s memory %s",
                     decode_vertices.ncalls , len(simplex_info), mem_used)
        integer = np.uint64(integer)
        start = not((integer & mask64) >> np.uint64(63))
        v0 = integer & mask21
        v1 = (integer & mask42) >> np.uint64(21)
        v2 = (integer & mask63) >> np.uint64(42)
        vertices = [v for v in [v0, v1, v2] if v != end]
        return pd.Series([start, vertices], index=["start", "vertices"])
    #    vertices = [start, v0, v1, v2]
    #    return pd.Series(vertices, index=["start", 0, 1, 2])
    decode_vertices.ncalls = 0

    LOG.info("Decode the simplices into simplex vertices")
    vertices = simplex_info.apply(decode_vertices)
    LOG.info("Done decoding to simplex vertices")

    vertices = (vertices.assign(sid=np.cumsum(vertices.start))
                .reset_index(drop=True))

    simplices = (vertices.set_index("sid").vertices
                 .groupby("sid").apply(np.hstack))

    if not test:
        return simplices

    return (vertices.vertices, simplices)





def bedge_counts(adjacency, nodes=None, simplices=None, **kwargs):
    """...
    adj : Adjacency matrix N * N
    simplices : sequence of 2D arrays that contain simplices by dimension.
    ~           The Dth array will be of shape N * D
    ~           where D is the dimension of the simplices
    """
    adj = adjacency

    if simplices is None:
        LOG.info("COMPUTE `bedge_counts(...)`: No argued simplices.")
        return bedge_counts(adj, nodes, list_simplices_by_dimension(adj), **kwargs)
    else:
        LOG.info("COMPUTE `bedge_counts(...): for simplices: %s ", simplices.shape)

    dense = np.array(adjacency.toarray(), dtype=int)

    def subset_adj(simplex):
        return dense[simplex].T[simplex]

    def count_bedges(simplices_given_dim):
        """..."""
        try:
            d_simplices = simplices_given_dim.get_value()
        except AttributeError:
            d_simplices = simplices_given_dim

        if d_simplices is None or d_simplices.shape[1] == 1:
            return np.nan

        return (pd.DataFrame(d_simplices, columns=range(d_simplices.shape[1]))
                .apply(subset_adj, axis=1)
                .agg("sum"))

    return simplices.apply(count_bedges)


def convex_hull(adj, node_properties):# --> topology
    """Return the convex hull of the sub gids in the 3D space using x,y,z position for gids"""
    pass


#######################################################
################## WEIGHTED NETWORKS ##################
#######################################################

def at_weight_edges(weighted_adj, threshold, method="strength"):
    """ Returns thresholded network on edges
    :param method: distance returns edges with weight smaller or equal than thresh
                   strength returns edges with weight larger or equal than thresh
                   assumes csr format for weighted_adj"""
    data=weighted_adj.data
    data_thresh=np.zeros(data.shape)
    if method == "strength":
        data_thresh[data>=threshold]=data[data>=threshold]
    elif method == "distance":
        data_thresh[data<=threshold]=data[data<=threshold]
    else:
        raise ValueError("Method has to be 'strength' or 'distance'")
    adj_thresh=weighted_adj.copy()
    adj_thresh.data=data_thresh
    adj_thresh.eliminate_zeros()
    return adj_thresh


def filtration_weights(adj, node_properties=None, method="strength"):
    """
    Returns the filtration weights of a given weighted adjacency matrix.
    :param method: distance smaller weights enter the filtration first
                   strength larger weights enter the filtration first

    TODO: Should there be a warning when the return is an empty array because the matrix is zero?
    """
    if method == "strength":
        return np.unique(adj.data)[::-1]

    if method == "distance":
        return np.unique(adj.data)

    raise ValueError("Method has to be 'strength' or 'distance'")


def bin_weigths(weights, n_bins=10, return_bins=False):
    '''Bins the np.array weights
    Input: np.array of floats, no of bins
    returns: bins, and binned data i.e. a np.array of the same shape as weights with entries the center value of its corresponding bin
    '''
    tol = 1e-8 #to include the max value in the last bin
    min_weight = weights.min()
    max_weight = weights.max() + tol
    step = (max_weight - min_weight) / n_bins
    bins = np.arange(min_weight, max_weight + step, step)
    digits = np.digitize(weights, bins)

    weights = (min_weight + step / 2) + (digits - 1) * step
    return (weights, bins) if return_bins else weights


def filtered_simplex_counts(adj, node_properties=None, method="strength",
                            binned=False, n_bins=10, threads=1,
                            **kwargs):
    '''Takes weighted adjancecy matrix returns data frame with filtered simplex counts where index is the weight
    method strength higher weights enter first, method distance smaller weights enter first'''
    from tqdm import tqdm
    adj = adj.copy()
    if binned==True:
        adj.data = bin_weigths(adj.data, n_bins=n_bins)

    weights = filtration_weights(adj, node_properties, method)

#    TODO: 1. Prove that the following is executed in the implementation that follows.
#    TODO: 2. If any difference, update the implementation
#    TODO: 3. Remove the reference code.
#    n_simplices = dict.fromkeys(weights)
#    for weight in tqdm(weights[::-1],total=len(weights)):
#        adj = at_weight_edges(adj, threshold=weight, method=method)
#        n_simplices[weight] = simplex_counts(adj, threads=threads)

    m = method
    def filter_weight(w):
        adj_w = at_weight_edges(adj, threshold=w, method=m)
        return simplex_counts(adj_w, threads=threads)

    n_simplices = {w: filter_weight(w) for w in weights[::-1]}
    return pd.DataFrame.from_dict(n_simplices, orient="index").fillna(0).astype(int)


def chunk_approx_and_dims(min_dim=0, max_dim=[], approximation=None):
    # Check approximation list is not too long and it's a list of integers
    assert (all([isinstance(item, int) for item in approximation])), 'approximation must be a list of integers'
    approximation = np.array(approximation)
    if max_dim == []:
        max_dim = np.inf
    assert (approximation.size - 1 <= max_dim - min_dim), "approximation list too long for the dimension range"

    # Split approximation into sub-vectors of same value to speed up computation
    diff = approximation[1:] - approximation[:-1]
    slice_indx = np.array(np.where(diff != 0)[0]) + 1
    dim_chunks = np.split(np.arange(approximation.size) + min_dim, slice_indx)
    if approximation[-1] == -1:
        dim_chunks[-1][-1] = -1
    else:
        if dim_chunks[-1][-1] < max_dim:
            dim_chunks.append([dim_chunks[-1][-1] + 1, max_dim])

    # Returned chuncked lists
    approx_chunks = []
    for j in range(len(dim_chunks)):
        if (approximation.size < max_dim - min_dim + 1) and approximation[-1] != -1 and j == len(dim_chunks) - 1:
            a = -1
        else:
            a = approximation[int(dim_chunks[j][0]) - min_dim]
        approx_chunks.append(a)
    return dim_chunks, approx_chunks


def persistence(weighted_adj, node_properties=None,
                min_dim=0, max_dim=[], directed=True, coeff=2, approximation=None,
                invert_weights=False, binned=False, n_bins=10, return_bettis=False,
                **kwargs):
    from pyflagser import flagser_weighted
    import numpy as np
    # Normalizing and binning data
    adj = weighted_adj.copy()
    if invert_weights == True:
        # Normalizing data between 0-1 and inverting order of the entries
        adj.data = (np.max(adj.data) - adj.data) / (np.max(adj.data) - np.min(adj.data))
    if binned == True:
        adj.data = bin_weigths(adj.data, n_bins=n_bins)

    # Sending computation to flagser
    # For single approximate value
    if approximation == None or isinstance(approximation, int):
        if min_dim != 0:
            LOG.info("Careful of pyflagser bug with range in dimension")
        out = flagser_weighted(adj, min_dimension=min_dim, max_dimension=max_dim, directed=True, coeff=2,
                               approximation=approximation)
        dgms = out['dgms']
        bettis = out['betti']
    # For approximate list
    else:
        # Chunk values to speed computations
        dim_chunks, approx_chunks = chunk_approx_and_dims(min_dim=min_dim, max_dim=max_dim, approximation=approximation)
        bettis = []
        dgms = []
        for dims_range, a in zip(dim_chunks, approx_chunks):
            n = dims_range[0]  # min dim for computation
            N = dims_range[-1]  # max dim for computation
            if N == -1:
                N = np.inf
            if a == -1:
                a = None
            LOG.info("Run betti for dim range %s-%s with approximation %s",n, N, a)
            if n != 0:
                LOG.info("Warning, possible bug in pyflagser when not running dimension range starting at dim 0")
            out = flagser_weighted(adj, min_dimension=n, max_dimension=N, directed=True, coeff=2, approximation=a)
            bettis = bettis + out['betti']
            dgms = dgms + out['dgms']
            LOG.info("out: %s",[out['dgms'][i].shape for i in range(len(out['dgms']))])
    if return_bettis == True:
        return dgms, bettis
    else:
        return dgms

#Tools for persistence
def num_cycles(B,D,thresh):
    #Given a persistence diagram (B,D) compute the number of cycles alive at tresh
    #Infinite bars have death values np.inf
    born=np.count_nonzero(B<=thresh)
    dead=np.count_nonzero(D<=thresh)
    return born-dead

def betti_curve(B,D):
    #Given a persistence diagram (B,D) compute its corresponding betti curve
    #Infinite bars have death values np.inf
    filt_values=np.concatenate([B,D])
    filt_values=np.unique(filt_values)
    filt_values=filt_values[filt_values!=np.inf]
    bettis=[]
    for thresh in filt_values:
        bettis.append(num_cycles(B,D,thresh))
    return filt_values,np.array(bettis)