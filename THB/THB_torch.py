import torch
import THB_eval
import numpy as np

class THBEval(torch.autograd.Function):
    @staticmethod
    def forward(ctx, ctrl_pts, Jm_array, tensor_prod, num_supp_bs_cumsum, device):
        ctx.save_for_backward(ctrl_pts, Jm_array, tensor_prod, num_supp_bs_cumsum)
        ctx.device = device
        if device=='cuda':
            return THB_eval.forward(ctrl_pts, Jm_array, tensor_prod, num_supp_bs_cumsum)
        else:
            return THB_eval.cpp_forward(ctrl_pts, Jm_array, tensor_prod, num_supp_bs_cumsum)

    @staticmethod
    def backward(ctx, grad_output):
        ctrl_pts, Jm_array, tensor_prod, num_supp_bs_cumsum = ctx.saved_tensors
        device = ctx.device
        if device=='cuda':
            grad_ctrl_pts = THB_eval.backward(grad_output, ctrl_pts, Jm_array, tensor_prod, num_supp_bs_cumsum)
        else:
            grad_ctrl_pts = THB_eval.cpp_backward(grad_output, ctrl_pts, Jm_array, tensor_prod, num_supp_bs_cumsum)
        return grad_ctrl_pts, None, None, None, None
    

def prepare_data_for_acceleration(PHI, ac_spans, num_supp_cumsum, ctrl_pts, ac_cells_ac_supp, fn_sh, device):
    max_lev = max(ctrl_pts.keys())
    nCP = np.zeros(max_lev+2, dtype=np.int_)
    num_supp_cumsum = torch.from_numpy(num_supp_cumsum).to(device=device)
    PHI = torch.from_numpy(PHI).to(device=device)
    CP_dim = ctrl_pts[0].shape[-1]
    for lev in range(1, max_lev+2):
        nCP[lev] = nCP[lev-1] + np.prod(fn_sh[lev-1])
    
    ctrl_pts = torch.vstack([torch.from_numpy(ctrl_pts[lev]).reshape(-1, CP_dim) for lev in range(max_lev+1)]).to(device=device)
    
    Jm = [nCP[fn_lev] + np.ravel_multi_index(fnIdx, fn_sh[fn_lev]) for cell_lev, cellIdx in ac_spans for fn_lev, fnIdx in ac_cells_ac_supp[cell_lev][cellIdx]]

    Jm = torch.tensor(Jm)
    # Jm_array = torch.vstack([torch.tensor([nCP[fn_lev]+np.ravel_multi_index(supp, fn_sh[fn_lev]) for fn_lev, supp in ac_cells_ac_supp[cell_lev][cellIdx]] for cell_lev, cellIdx in ac_spans)]).to(device=device)

    return ctrl_pts, Jm, PHI, num_supp_cumsum, device