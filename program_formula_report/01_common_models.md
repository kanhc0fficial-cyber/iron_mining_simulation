# 公共数学模型

来源：`sim/rng.py`、`sim/utils/buffer.py`、`sim/utils/pid.py`、`sim/utils/sensor.py`、`sim/utils/thermal.py`、`sim/simulator.py`。

## 记号

- `clip(x,a,b)=min(max(x,a),b)`。
- `sigmoid(x)=1/(1+exp(-x))`，程序在正负区间分支实现以避免溢出。
- `N(0,sigma)` 表示均值为 0、标准差为 `sigma` 的高斯随机数。
- 时间步长为 `dt`。

## 随机数派生

`RNGFactory(master_seed)` 使用一个主随机数发生器为每个子系统生成独立种子：

```text
seed_name = master_rng.integers(0, 2^31)
rng_name = default_rng(seed_name)
```

同名子系统重复请求时返回同一 `Generator` 实例。

## 环形缓冲时滞

`RingBuffer(capacity, default)` 用固定数组保存历史值。写入：

```text
buf[head] = value
head = (head + 1) mod capacity
```

读取 `delay_steps` 步前的值：

```text
idx = (head - 1 - delay_steps) mod capacity
value_delay = buf[idx]
```

因此 `delay_steps=0` 为最近一次写入值。

## 传感器噪声、漂移与故障

白噪声测量：

```text
y = x + N(0, sigma)
```

随机游走漂移：

```text
b_new = b + N(0, sigma_b)
y = x + b_new
```

故障注入：

```text
y = fault_val,  若 U(0,1) < p_fault
y = x,          否则
```

## 离散 PID

误差：

```text
e_k = setpoint - measurement
D_k = (e_k - e_{k-1}) / dt
raw_u = Kp*e_k + I_{k-1} + Kd*D_k
```

若开启反积分饱和且 `raw_u` 已超出 `[u_min,u_max]`，本步不积分；否则：

```text
I_k = I_{k-1} + Ki*e_k*dt
```

输出：

```text
u_k = clip(Kp*e_k + I_k + Kd*D_k, u_min, u_max)
```

## 一阶热模型：前向欧拉

`FirstOrderThermal.step` 使用：

```text
dT/dt = (Q_heat - k_cool*(T - T_amb)) / tau
T_{k+1} = T_k + dt*dT/dt + noise
```

对应稳态温度：

```text
T_ss = T_amb + Q_heat/k_cool
```

## ZOH 一阶模型

塔磨和浮选中还使用精确零阶保持离散化：

```text
phi = exp(-dt/tau)
x_{k+1} = x_ss + (x_k - x_ss)*phi + noise
```

数组版本同式逐元素计算。
