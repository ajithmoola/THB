import numpy as np
from numba import njit
import jax.numpy as jnp
from jax import jit, vmap, jacfwd, lax


def refine_knotvector(knotvector, p):
    knots = np.unique(knotvector)
    mids = 0.5 * (knots[1:] + knots[:-1])
    refined_knotvector = np.concatenate(
        [
            knotvector[:p],
            np.unique(np.sort(np.concatenate([knots, mids]))),
            knotvector[-p:],
        ]
    )
    return refined_knotvector


def generate_parametric_coordinates(shape):
    ndim = len(shape)
    pts = np.hstack(
        tuple(
            map(
                lambda x: x.reshape(-1, 1),
                np.meshgrid(
                    *[
                        np.linspace(1e-5, 1, shape[dim], endpoint=False)
                        for dim in range(ndim)
                    ]
                ),
            )
        )
    )
    return pts


def grevilleAbscissae(fn_sh, degrees, knotvectors):
    ndim = len(fn_sh)
    CP = np.zeros((*fn_sh, ndim))

    for pt in np.ndindex(fn_sh):
        CP[pt] = np.array(
            [
                np.sum(knotvectors[dim][pt[dim] + 1 : pt[dim] + degrees[dim] + 1])
                / degrees[dim]
                for dim in range(ndim)
            ]
        )

    return CP


def compute_tensor_product(args):
    if len(args) == 2:
        return np.einsum("i, j -> ij", *args)
    if len(args) == 3:
        return np.einsum("i, j, k -> ijk", *args)


@jit
def compute_tensor_product_jax(basis_fns):
    if len(basis_fns) == 3:
        return jnp.einsum("i,j,k->ijk", *basis_fns)
    elif len(basis_fns) == 2:
        return jnp.einsum("i,j->ij", *basis_fns)


def findSpan(n, p, u, U):
    if u == U[n + 1]:
        return n
    low = p
    high = n + 1
    mid = int((low + high) / 2)
    while u < U[mid] or u >= U[mid + 1]:
        if u < U[mid]:
            high = mid
        else:
            low = mid
        mid = int((low + high) / 2)
    return mid


@jit
def find_span_array_jax(params, U, degree):
    n = len(U) - degree - 1
    indices = jnp.searchsorted(U, params, side="right") - 1
    indices = jnp.where(indices > n, n, indices)
    indices = jnp.where(params == U[n + 1], n, indices)
    return indices


def basisFun(i, u, p, U):
    N = np.zeros((p + 1))
    N[0] = 1
    left = np.zeros((p + 1))
    right = np.zeros((p + 1))
    for j in range(1, p + 1):
        left[j] = u - U[i + 1 - j]
        right[j] = U[i + j] - u
        saved = 0
        for r in range(0, j):
            temp = N[r] / (right[r + 1] + left[j - r])
            N[r] = saved + right[r + 1] * temp
            saved = left[j - r] * temp
        N[j] = saved

    return N


@jit
def divisionbyzero(numerator, denominator):
    force_zero = jnp.logical_and(numerator == 0, denominator == 0)

    return jnp.where(force_zero, jnp.float32(0.0), numerator) / jnp.where(
        force_zero, jnp.float32(1.0), denominator
    )


# def basisFun_vectorized(params1d, knotvector, degree):
#     U = jnp.expand_dims(params1d, -1)
#     knots = jnp.expand_dims(knotvector, 0)

#     spans = find_span_array_jax(params1d, knotvector, degree) - degree

#     K = jnp.where(
#         knots == knotvector[-1], knotvector[-1] + jnp.finfo(U.dtype).eps, knots
#     )

#     t1 = U >= K[..., :-1]
#     t2 = U < K[..., 1:]

#     N = (t1 * t2) + 0.0

#     for p in range(1, degree + 1):

#         term1 = divisionbyzero(
#             N[..., :-1] * (U - K[..., : -p - 1]), K[..., p:-1] - K[..., : -p - 1]
#         )

#         term2 = divisionbyzero(
#             N[..., 1:] * (K[..., p + 1 :] - U), K[..., p + 1 :] - K[..., 1:-p]
#         )

#         N = term1 + term2

#     n = params1d.shape[0]
#     result = jnp.zeros((n, degree + 1))

#     idx = jnp.arange(degree + 1)
#     span_indices = spans[:, None] + idx[None, :]
#     result = N[jnp.arange(n)[:, None], span_indices]

#     return result


def basisFun_jax(param, knotvector, degree):
    params1d = jnp.array(param)
    U = jnp.expand_dims(params1d, -1)
    knots = jnp.expand_dims(knotvector, 0)

    spans = find_span_array_jax(params1d, knotvector, degree) - degree

    K = jnp.where(
        knots == knotvector[-1], knotvector[-1] + jnp.finfo(U.dtype).eps, knots
    )

    t1 = U >= K[..., :-1]
    t2 = U < K[..., 1:]

    N = (t1 * t2) + 0.0

    for p in range(1, degree + 1):

        term1 = divisionbyzero(
            N[..., :-1] * (U - K[..., : -p - 1]), K[..., p:-1] - K[..., : -p - 1]
        )

        term2 = divisionbyzero(
            N[..., 1:] * (K[..., p + 1 :] - U), K[..., p + 1 :] - K[..., 1:-p]
        )

        N = term1 + term2
    result = jnp.zeros((1, degree + 1))

    idx = jnp.arange(degree + 1)
    span_indices = spans + idx
    result = N[jnp.arange(1)[:, None], span_indices]

    return result


def basis_fns_vmap(params, knotvector, degree):
    return vmap(basisFun_jax, in_axes=(0, None, None))(
        jnp.expand_dims(params, -1), knotvector, degree
    ).squeeze()


def der_basis_fns_vmap(params, knotvector, degree):
    return vmap(jacfwd(basisFun_jax, argnums=0), in_axes=(0, None, None))(
        jnp.expand_dims(params, -1), knotvector, degree
    ).squeeze()


@njit
def assemble_Tmatrix(knotVec, newKnotVec, knotVec_len, newKnotVec_len, p):
    # TODO: convert to c++ function
    T1 = np.zeros((newKnotVec_len - 1, knotVec_len - 1))

    for i in range(newKnotVec_len - 1):
        for j in range(knotVec_len - 1):
            if (newKnotVec[i] >= knotVec[j]) and (newKnotVec[i] < knotVec[j + 1]):
                T1[i, j] = 1

    for q in range(1, p + 1):
        T2 = np.zeros(((newKnotVec_len - q - 1), (knotVec_len - q - 1)))
        for i in range(newKnotVec_len - q - 1):
            for j in range(knotVec_len - q - 1):
                if (knotVec[j + q] - knotVec[j] == 0) and (
                    knotVec[j + q + 1] - knotVec[j + 1] != 0
                ):
                    T2[i, j] = (
                        (knotVec[j + q + 1] - newKnotVec[i + q])
                        / (knotVec[j + q + 1] - knotVec[j + 1])
                        * T1[i, j + 1]
                    )
                if (knotVec[j + q] - knotVec[j] != 0) and (
                    knotVec[j + q + 1] - knotVec[j + 1] == 0
                ):
                    T2[i, j] = (
                        (newKnotVec[i + q] - knotVec[j])
                        / (knotVec[j + q] - knotVec[j])
                        * T1[i, j]
                    )
                if (knotVec[j + q] - knotVec[j] != 0) and (
                    knotVec[j + q + 1] - knotVec[j + 1] != 0
                ):
                    T2[i, j] = (newKnotVec[i + q] - knotVec[j]) / (
                        knotVec[j + q] - knotVec[j]
                    ) * T1[i, j] + (knotVec[j + q + 1] - newKnotVec[i + q]) / (
                        knotVec[j + q + 1] - knotVec[j + 1]
                    ) * T1[
                        i, j + 1
                    ]

        T1 = T2
    return T1


def bezier_extraction(knot, p):
    m = len(knot) - p - 1
    a = p + 1
    b = a + 1
    ne = 0
    C = []
    C.append(np.eye(p + 1, p + 1))
    alphas = {}

    while b <= m:
        C.append(np.eye(p + 1, p + 1))
        i = b
        while b <= m and knot[b] == knot[b - 1]:
            b = b + 1

        multiplicity = b - i + 1
        if multiplicity < p:
            numerator = knot[b - 1] - knot[a - 1]
            for j in range(p, multiplicity, -1):
                alphas[j - multiplicity] = numerator / (knot[a + j - 1] - knot[a - 1])

            r = p - multiplicity
            for j in range(1, r + 1):
                save = r - j + 1
                s = multiplicity + j
                for k in range(p + 1, s, -1):
                    alpha = alphas[k - s]
                    C[ne][:, k - 1] = (
                        alpha * C[ne][:, k - 1] + (1 - alpha) * C[ne][:, k - 2]
                    )
                if b <= m:
                    C[ne + 1][save - 1 : save + j, save - 1] = C[ne][p - j : p + 1, p]
            ne = ne + 1
            if b <= m:
                a = b
                b = b + 1

        elif multiplicity == p:
            if b <= m:
                ne = ne + 1
                a = b
                b = b + 1
    return C


if __name__ == "__main__":
    kv = np.array([0, 0, 0, 0, 1, 2, 3, 4, 4, 4, 4])
    deg = 3
    num_knots = len(np.unique(kv))
    C, nb = bezier_extraction(kv, deg)
    print(C, nb, num_knots)
