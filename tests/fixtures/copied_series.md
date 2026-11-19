# 无穷级数综合证明题（复制格式回归样例）

证明级数

\\[ \boxed{\sum\_{n=1}^{\infty}\sum\_{k=1}^{\infty} \frac{(-1)^{[\sqrt n]}}{n^2+k^2}} \\]

收敛，其中 \\([x]\\) 表示不超过 \\(x\\) 的最大整数。

## 积分估计

令 \\(a_n=\sum\_{k=1}^{\infty}\frac1{n^2+k^2}\\)。

\\[ \int_1^\infty g(t)\,dt \le\sum\_{k=1}^\infty g(k) \le\int_0^\infty g(t)\,dt \\]

\\[ \int_0^\infty\frac{dt}{n^2+t^2} =\frac1n\left[\arctan\frac tn\right]\_0^\infty =\frac{\pi}{2n} \\]

\\[ 0\le\frac{\pi}{2n}-a_n \le\int_0^1\frac{dt}{n^2+t^2} \le\frac1{n^2} \\]

\\[ \boxed{a_n=\frac{\pi}{2n}+O\left(\frac1{n^2}\right)} \\]

\\[ \begin{aligned} \sum\_{n=1}^{\infty}(-1)^{[\sqrt n]}a_n &=\frac\pi2\sum\_{n=1}^{\infty} \frac{(-1)^{[\sqrt n]}}n\\\ &\quad+\sum\_{n=1}^{\infty}(-1)^{[\sqrt n]} O\left(\frac1{n^2}\right) \end{aligned} \\]

## 按平方数分组

\\[ \begin{aligned} &\sum\_{n=1}^{\infty}\frac{(-1)^{[\sqrt n]}}n\\\ ={}&-\left(1+\frac12+\frac13\right)\\\ &+\left(\frac14+\cdots+\frac18\right)\\\ &-\left(\frac19+\cdots+\frac1{15}\right)\\\ &+\cdots \end{aligned} \\]

\\[ b_m=\sum\_{n=m^2}^{(m+1)^2-1}\frac1n \\]

\\[ \int\_{m^2}^{(m+1)^2}\frac{dt}{t} \le b_m \le\int\_{m^2}^{(m+1)^2}\frac{dt}{t} +\frac1{m^2} \\]

\\[ \begin{aligned} \int\_{m^2}^{(m+1)^2}\frac{dt}{t} &=\ln\frac{(m+1)^2}{m^2}\\\ &=2\ln\left(1+\frac1m\right) \end{aligned} \\]

\\[ \boxed{b_m=2\ln\left(1+\frac1m\right)+\varepsilon_m} \\]

\\[ 2\sum\_{m=1}^{\infty}(-1)^m\ln\left(1+\frac1m\right) +\sum\_{m=1}^{\infty}(-1)^m\varepsilon_m \\]

\\[ \ln\left(1+\frac1m\right)\downarrow0 \\]

\\[ 0\le\sum\_{n=m^2}^{(m+1)^2-1}\frac1n \le\frac{2m+1}{m^2}\to0 \\]

## 条件收敛

\\[ a_n \ge\sum\_{k=1}^{n}\frac1{2n^2} =\frac1{2n} \\]

\\[ \sum\_{n=1}^\infty a_n \ge\frac12\sum\_{n=1}^\infty\frac1n =\infty \\]

\\[ \boxed{\text{双重级数} \longrightarrow \text{积分估计} \longrightarrow \text{平方数分组} \longrightarrow \text{交错级数收敛}} \\]
