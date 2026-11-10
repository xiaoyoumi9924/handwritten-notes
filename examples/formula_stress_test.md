# 中英混排与公式专项样张

这份样张用于检查手写效果下的公式结构、文字基线、字符间距和页面边界。中文说明与 English text 会和行内公式混排，公式尽量保持原有数学排版关系。

## 行内公式与上下标

设物体在时间 \(t\) 内运动。位移为 \(s\)，初速度为 \(v_0\)，加速度为 \(a\)，因此有 \(s=v_0t+\frac{1}{2}at^2\)。Newton's second law is written as \(F=ma\), and the kinetic energy is \(E_k=\frac{1}{2}mv^2\)。这些公式中的上标、下标与中文标点应保持清楚。

## 分数、根式与长表达式

当 \(a,b,c>0\) 时，可以比较下面的公式高度和根号覆盖范围：

$$
x_{1,2}=\frac{-b\pm\sqrt{b^2-4ac}}{2a}
$$

带有嵌套分式的表达式：

$$
R=\frac{1}{1+\frac{1}{1+\frac{1}{x}}}
$$

英文说明：The following expression is intentionally longer, so it checks scaling and clipping near the line width.

$$
f(x)=\frac{(x+1)^2(x-1)^2}{\sqrt{x^2+1}}+\frac{\alpha x+\beta}{\gamma+\Delta x}
$$

## 求和、积分与希腊字母

数列求和与定积分中的上下限不应挤压相邻字符：

$$
\sum_{i=1}^{n} i=\frac{n(n+1)}{2}, \qquad \int_{0}^{1} x^2\,dx=\frac{1}{3}
$$

误差项使用希腊字母表示：

$$
\varepsilon=\left|\frac{x-x_0}{x_0}\right|\times100\%, \qquad \Delta y\approx f'(x)\Delta x
$$

## 矩阵与分段函数

矩阵元素需要行列对齐，左右括号要包住全部内容：

$$
\begin{bmatrix} 1 & x_1 & x_1^2 \\ 1 & x_2 & x_2^2 \\ 1 & x_3 & x_3^2 \end{bmatrix}
$$

分段函数需要完整保留大括号、条件和行距：

$$
f(x)=\begin{cases} x^2, & x\ge0 \\ -x, & x<0 \end{cases}
$$

## 多行推导与等号对齐

下面的连续变形检查换行和等号列对齐：

$$
\begin{aligned}
(x+1)^2 &= x^2+2x+1 \\
        &= (x-1)^2+4x \\
        &= x^2-2x+1+4x
\end{aligned}
$$

若 \(x\ne0\)，则另一个等价推导为：

$$
\begin{aligned}
\frac{x^2-1}{x-1} &= \frac{(x-1)(x+1)}{x-1} \\
                  &= x+1
\end{aligned}
$$

## 中文与 English 正文混排

实验记录中常会在中文解释后直接给出公式，例如：当温度变化量为 ΔT 时，\(Q=cm\Delta T\)。For a constant speed \(v\), the distance after time \(t\) is \(d=vt\)。请观察行内公式是否和中英文正文共用自然的视觉基线，标点和空格是否易读。
