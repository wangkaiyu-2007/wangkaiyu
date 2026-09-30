"""系统与统计工具。

包含 2 个 Tool：
- get_stats    医院经营统计
- get_health   健康检查
"""

from client import _get


def register_system_tools(mcp) -> None:
    """注册本模块所有 Tool。"""

    @mcp.tool()
    def get_stats(top: int = 5) -> dict:
        """医院经营统计（收入/种类/医生排行）。

        top: 各排行返回条数，默认 5
        返回: {totalPets, totalRecords, totalCharges, totalRevenue, averageCost, maxCost,
              bySpecies, byStatus, byDoctor, revenueByDoctor, ...}
        """
        return _get("/api/v1/stats", {"top": top})

    @mcp.tool()
    def get_health() -> dict:
        """健康检查：服务状态、运行时长、数据库文件与宠物总数。

        返回: {status, uptime, dbFile, petCount, timestamp}
        """
        return _get("/health")