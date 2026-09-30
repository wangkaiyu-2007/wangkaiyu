"""宠物档案工具（第一版 + 写操作 + 高级查询）。

包含 9 个 Tool：
- list_pets        查询宠物列表（多参数筛选 + 排序 + 分页）
- get_pet          按 ID 查询单个宠物完整档案
- search_pets      全文检索宠物
- top_spenders     消费排行榜
- cost_range_pets  按总花费区间查询
- create_pet       创建新宠物档案
- update_pet       全量更新宠物档案
- patch_pet        局部更新宠物档案
- delete_pet       删除宠物档案
"""

from client import _get, _post, _put, _patch, _delete


def register_pet_crud_tools(mcp) -> None:
    """注册本模块所有 Tool。"""

    @mcp.tool()
    def list_pets(
        page: int = 1,
        page_size: int = 20,
        species: str | None = None,
        doctor: str | None = None,
        disease: str | None = None,
        status: str | None = None,
        owner_name: str | None = None,
        owner_phone: str | None = None,
        sort_by: str = "createdAt",
        order: str = "desc",
    ) -> dict:
        """查询宠物列表，支持按种类/医生/疾病/状态/主人筛选、排序和分页。

        species 取值: 犬/猫/兔/鸟/仓鼠/爬宠/其他
        status 取值: 待就诊/就诊中/住院中/已康复/慢性病随访
        sort_by 取值: id/name/ownerName/species/doctor/disease/status/totalCost/visitCount/createdAt/updatedAt
        order 取值: asc/desc
        返回: {items, total, page, pageSize, totalPages, totalCost}
        """
        params: dict = {"page": page, "pageSize": page_size}
        if species:
            params["species"] = species
        if doctor:
            params["doctor"] = doctor
        if disease:
            params["disease"] = disease
        if status:
            params["status"] = status
        if owner_name:
            params["ownerName"] = owner_name
        if owner_phone:
            params["ownerPhone"] = owner_phone
        if sort_by:
            params["sortBy"] = sort_by
        if order:
            params["order"] = order
        return _get("/api/v1/pets", params)

    @mcp.tool()
    def get_pet(id: str) -> dict:
        """按 ID 查询单个宠物档案，包含完整信息（病历、消费明细、费用汇总）。

        id 格式: PET-000001, PET-000002, ...
        宠物不存在时抛中文错误提示。
        """
        return _get(f"/api/v1/pets/{id}")

    @mcp.tool()
    def search_pets(q: str) -> dict:
        """全文检索宠物（跨字段，空格分词 AND 匹配）。

        检索范围：宠物姓名、种类、品种、主人、医生、疾病、状态、病历全文、收费项目。
        示例: q="肠胃炎"、q="犬 张三"、q="骨折 李医生"
        """
        return _get("/api/v1/pets/search", {"q": q})

    @mcp.tool()
    def top_spenders(limit: int = 5) -> dict:
        """消费排行榜（按在医院总花费降序）。

        limit: 返回条数（1-100），默认 5
        返回: {limit, items, totalCost, total}
        """
        return _get("/api/v1/pets/top-spenders", {"limit": limit})

    @mcp.tool()
    def cost_range_pets(
        min_cost: float | None = None,
        max_cost: float | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """按总花费区间查询宠物（自动按花费降序）。

        min_cost: 最低总花费（元）
        max_cost: 最高总花费（元）
        返回: {items, total, page, pageSize, totalPages, totalCost}
        示例: cost_range_pets(min_cost=500, max_cost=5000)
        """
        params: dict = {"page": page, "pageSize": page_size}
        if min_cost is not None:
            params["min"] = min_cost
        if max_cost is not None:
            params["max"] = max_cost
        return _get("/api/v1/pets/cost-range", params)

    @mcp.tool()
    def create_pet(
        name: str,
        species: str,
        owner_name: str,
        owner_phone: str,
        doctor: str,
        disease: str,
        status: str = "待就诊",
        breed: str | None = None,
        gender: str | None = None,
        age_months: int | None = None,
        color: str | None = None,
        chip_no: str | None = None,
        owner_addr: str | None = None,
        allergy: str | None = None,
        note: str | None = None,
    ) -> dict:
        """创建新宠物档案。

        参数:
            name: 宠物姓名
            species: 种类（犬/猫/兔/鸟/仓鼠/爬宠/其他）
            owner_name: 主人姓名
            owner_phone: 主人电话
            doctor: 主治医生
            disease: 疾病
            status: 就诊状态（待就诊/就诊中/住院中/已康复/慢性病随访），默认"待就诊"
            breed: 品种（可选）
            gender: 性别（公/母，可选）
            age_months: 月龄（可选）
            color: 毛色（可选）
            chip_no: 芯片号（可选）
            owner_addr: 主人住址（可选）
            allergy: 过敏史（可选）
            note: 备注（可选）

        返回: 创建的宠物档案对象
        """
        pet_data: dict = {
            "name": name,
            "species": species,
            "ownerName": owner_name,
            "ownerPhone": owner_phone,
            "doctor": doctor,
            "disease": disease,
            "status": status,
        }
        if breed is not None:
            pet_data["breed"] = breed
        if gender is not None:
            pet_data["gender"] = gender
        if age_months is not None:
            pet_data["ageMonths"] = age_months
        if color is not None:
            pet_data["color"] = color
        if chip_no is not None:
            pet_data["chipNo"] = chip_no
        if owner_addr is not None:
            pet_data["ownerAddr"] = owner_addr
        if allergy is not None:
            pet_data["allergy"] = allergy
        if note is not None:
            pet_data["note"] = note
        return _post("/api/v1/pets", json=pet_data)

    @mcp.tool()
    def update_pet(
        id: str,
        name: str,
        species: str,
        owner_name: str,
        owner_phone: str,
        doctor: str,
        disease: str,
        status: str,
        breed: str | None = None,
        gender: str | None = None,
        age_months: int | None = None,
        color: str | None = None,
        chip_no: str | None = None,
        owner_addr: str | None = None,
        allergy: str | None = None,
        note: str | None = None,
    ) -> dict:
        """全量更新宠物档案（未传字段会清空）。

        参数:
            id: 宠物ID（格式: PET-000001）
            name: 宠物姓名
            species: 种类（犬/猫/兔/鸟/仓鼠/爬宠/其他）
            owner_name: 主人姓名
            owner_phone: 主人电话
            doctor: 主治医生
            disease: 疾病
            status: 就诊状态（待就诊/就诊中/住院中/已康复/慢性病随访）
            breed: 品种（可选）
            gender: 性别（公/母，可选）
            age_months: 月龄（可选）
            color: 毛色（可选）
            chip_no: 芯片号（可选）
            owner_addr: 主人住址（可选）
            allergy: 过敏史（可选）
            note: 备注（可选）

        返回: 更新后的宠物档案对象
        """
        pet_data: dict = {
            "name": name,
            "species": species,
            "ownerName": owner_name,
            "ownerPhone": owner_phone,
            "doctor": doctor,
            "disease": disease,
            "status": status,
        }
        if breed is not None:
            pet_data["breed"] = breed
        if gender is not None:
            pet_data["gender"] = gender
        if age_months is not None:
            pet_data["ageMonths"] = age_months
        if color is not None:
            pet_data["color"] = color
        if chip_no is not None:
            pet_data["chipNo"] = chip_no
        if owner_addr is not None:
            pet_data["ownerAddr"] = owner_addr
        if allergy is not None:
            pet_data["allergy"] = allergy
        if note is not None:
            pet_data["note"] = note
        return _put(f"/api/v1/pets/{id}", json=pet_data)

    @mcp.tool()
    def patch_pet(
        id: str,
        name: str | None = None,
        species: str | None = None,
        owner_name: str | None = None,
        owner_phone: str | None = None,
        doctor: str | None = None,
        disease: str | None = None,
        status: str | None = None,
        breed: str | None = None,
        gender: str | None = None,
        age_months: int | None = None,
        color: str | None = None,
        chip_no: str | None = None,
        owner_addr: str | None = None,
        allergy: str | None = None,
        note: str | None = None,
    ) -> dict:
        """局部更新宠物档案（只更新传入的字段）。

        参数:
            id: 宠物ID（格式: PET-000001）
            name: 宠物姓名（可选）
            species: 种类（犬/猫/兔/鸟/仓鼠/爬宠/其他，可选）
            owner_name: 主人姓名（可选）
            owner_phone: 主人电话（可选）
            doctor: 主治医生（可选）
            disease: 疾病（可选）
            status: 就诊状态（待就诊/就诊中/住院中/已康复/慢性病随访，可选）
            breed: 品种（可选）
            gender: 性别（公/母，可选）
            age_months: 月龄（可选）
            color: 毛色（可选）
            chip_no: 芯片号（可选）
            owner_addr: 主人住址（可选）
            allergy: 过敏史（可选）
            note: 备注（可选）

        返回: 更新后的宠物档案对象
        """
        pet_data: dict = {}
        if name is not None:
            pet_data["name"] = name
        if species is not None:
            pet_data["species"] = species
        if owner_name is not None:
            pet_data["ownerName"] = owner_name
        if owner_phone is not None:
            pet_data["ownerPhone"] = owner_phone
        if doctor is not None:
            pet_data["doctor"] = doctor
        if disease is not None:
            pet_data["disease"] = disease
        if status is not None:
            pet_data["status"] = status
        if breed is not None:
            pet_data["breed"] = breed
        if gender is not None:
            pet_data["gender"] = gender
        if age_months is not None:
            pet_data["ageMonths"] = age_months
        if color is not None:
            pet_data["color"] = color
        if chip_no is not None:
            pet_data["chipNo"] = chip_no
        if owner_addr is not None:
            pet_data["ownerAddr"] = owner_addr
        if allergy is not None:
            pet_data["allergy"] = allergy
        if note is not None:
            pet_data["note"] = note
        return _patch(f"/api/v1/pets/{id}", json=pet_data)

    @mcp.tool()
    def delete_pet(id: str) -> dict:
        """删除宠物档案。

        参数:
            id: 宠物ID（格式: PET-000001）

        返回: 删除结果
        """
        return _delete(f"/api/v1/pets/{id}")