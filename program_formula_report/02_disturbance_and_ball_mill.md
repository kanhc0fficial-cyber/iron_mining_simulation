# 外生扰动与球磨输入

来源：`sim/layers/disturbance.py`、`sim/layers/ball_mill.py`、`sim/config.py`。

## 外生扰动 `_x_d1` 到 `_x_d4`

`d1` 与 `d2` 使用相关 OU/AR(1) 噪声。令标准正态向量：

```text
z = [z1, z2]^T,  z_i ~ N(0,1)
```

Cholesky 矩阵：

```text
L = [[s1, 0],
     [rho*s2, s2*sqrt(max(1-rho^2,0))]]
```

其中正常模式 `s1=d1_sigma`，开环模式 `s1=d1_sigma*d1_sigma_open_factor`，`s2=d2_sigma`，`rho=cov_d1d2`。

相关噪声：

```text
[eta1, eta2]^T = L*z
```

状态更新：

```text
xi_d1,k = d1_phi*xi_d1,k-1 + eta1
xi_d2,k = d2_phi*xi_d2,k-1 + eta2
xi_d3,k = d3_phi*xi_d3,k-1 + N(0,d3_sigma)
xi_d4,k = d4_phi*xi_d4,k-1 + N(0,d4_sigma)
```

输出：

```text
_x_d1 = clip(d1_mean + xi_d1, d1_min, d1_max)
_x_d2 = clip(d2_mean + xi_d2, d2_min, d2_max)
_x_d3 = clip(d3_mean + xi_d3, d3_min, d3_max)
_x_d4 = clip(d4_mean + xi_d4, d4_min, d4_max)
```

程序语义中：

- `_x_d1`：球磨溢流 TFe 品位。
- `_x_d2`：碳酸铁含量，后续影响 pH。
- `_x_d3`：可磨性系数。
- `_x_d4`：公共管网水压 MPa。

## 球磨 AR(1) 边界量

球磨三条线共享慢变残差：

```text
xi_m,k   = m_ball_phi*xi_m,k-1 + N(0,m_ball_sigma)
xi_rho,k = rho_ball_phi*xi_rho,k-1 + N(0,rho_ball_sigma)
xi_d80,k = d80_ball_phi*xi_d80,k-1 + N(0,d80_ball_sigma)
```

每条线的独立扰动：

```text
ind_noise_i = N(0, m_ball_sigma*sqrt(1-rho_lines))
m_line_i = m_ball_mean + xi_m + ind_noise_i
```

三线合计湿质量流量：

```text
_x_m_ball = sum_i clip(m_line_i, m_ball_min, m_ball_max),  i=1..n_lines
```

球磨溢流浓度：

```text
_x_rho_ball = clip(rho_ball_mean + xi_rho, rho_ball_min, rho_ball_max)
```

可磨性修正后的球磨溢流粒度：

```text
d80_raw = d80_ball_mean / _x_d3 + xi_d80
_x_d80_ball = clip(d80_raw, d80_ball_min, d80_ball_max)
```

超细粒含量：

```text
f25_raw = f25_max * sigmoid(k_f25*(d80_ref - _x_d80_ball) + bias_f25) + N(0,sigma_f25)
_x_f25_ball = clip(f25_raw, 0, 1)
```

这意味着程序中 `_x_d3` 越大，`_x_d80_ball` 越小；`d80` 越小，`_x_f25_ball` 经反 S 关系越大。
