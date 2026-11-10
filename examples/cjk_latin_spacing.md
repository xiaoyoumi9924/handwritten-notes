# 中文英文衔接与公式混排

这段样例专门检查中英文直接相邻时的留白，原文没有手动插空格。

本工具会读取Markdown文档并返回PDF结果，其中API负责解析，JSON数据保存选项，Python脚本执行转换。

当用户输入HelloWorld时，系统应保留英文单词的自然字距；输出状态success后，中文说明仍要清楚。版本号v2.1、GPU加速和tokenCount也用于检查数字与术语的衔接。

下面检查行内公式边界：质量m与速度v满足动能关系\(E_k=\frac{1}{2}mv^2\)，计算结果写入result变量。英语句子里，the value of x is \(\frac{-b+\sqrt{b^2-4ac}}{2a}\), which remains on the math path.

有空格的情况不应再次加宽：中文 English English中文，中文 version2 version2中文；标点与括号也应自然：响应码200OK（status OK）。

For comparison, a plain English paragraph remains unchanged: write one short note, check its letter spacing, and keep a little room around punctuation.
