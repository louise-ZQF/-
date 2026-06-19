"""SMTP 邮件发送（QQ / 163 / 126 / Gmail）。

QQ/163 注意：登录用的是「授权码」而非邮箱密码，需先在邮箱网页端
「设置 → 账户 → POP3/SMTP 服务」中开启并生成授权码。
"""
from __future__ import annotations

import smtplib
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Optional

from .config import EmailConfig


def send_email(cfg: EmailConfig, subject: str, html_body: str,
               text_body: Optional[str] = None) -> bool:
    """发送一封 HTML 邮件（带纯文本兜底）。成功返回 True。"""
    if not cfg.configured:
        print("[email] 邮件未配置（缺少 SMTP_HOST/SMTP_USER/SMTP_PASSWORD/MAIL_TO），跳过发送。")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header("基金分析助手", "utf-8")), cfg.sender))
    msg["To"] = ", ".join(cfg.recipients)
    if text_body:
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        if cfg.use_ssl:
            server = smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=30)
        else:
            server = smtplib.SMTP(cfg.host, cfg.port, timeout=30)
            server.starttls()
        with server:
            server.login(cfg.user, cfg.password)
            server.sendmail(cfg.sender, cfg.recipients, msg.as_string())
        print(f"[email] 已发送至 {', '.join(cfg.recipients)}")
        return True
    except (smtplib.SMTPException, OSError) as e:
        print(f"[email] 发送失败：{e}")
        return False
