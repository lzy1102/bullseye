"""
Future Gateways - Chinese futures market trading gateways

Supports various Chinese futures protocols:
- CTP: 综合交易平台 (SimNow 仿真/实盘)
- MiniCTP: 迷你CTP
- FEMAS: 飞马
- UFT: 恒生UFT
"""

from .ctp_gateway import CtpGateway

__all__ = ["CtpGateway"]

# Additional gateways can be imported when implemented:
# from .mini_gateway import MiniGateway
# from .femas_gateway import FemasGateway
# from .uft_gateway import UftGateway
