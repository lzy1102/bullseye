"""
Stock Gateways - Chinese stock market trading gateways

Supports various Chinese stock broker protocols:
- XTP: 中泰证券
- TORA: 华鑫奇点
- OST: 东证
- EMT: 东方财富
"""

from .xtp_gateway import XtpGateway

__all__ = ["XtpGateway"]

# Additional gateways can be imported when implemented:
# from .tora_gateway import ToraGateway
# from .ost_gateway import OStGateway
# from .emt_gateway import EmtGateway
