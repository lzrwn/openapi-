# 商城系统接口文档（素材样例）

> 本文档为测试素材，混合了接口描述、curl 请求样例与源码片段，
> 部分信息刻意不完整或有出入，用于验证 agent 的提取 / 融合 / 冲突标记能力。

## 1. 商品模块

### 1.1 商品列表

查询商品列表，支持按关键字搜索与分页。

| 参数 | 位置 | 类型 | 必填 | 说明 |
|---|---|---|---|---|
| keyword | query | string | 否 | 商品名关键字，模糊匹配 |
| page | query | integer | 否 | 页码，从 1 开始 |
| page_size | query | integer | 否 | 每页条数，默认 10，最大 100 |

### 1.2 商品详情

路径参数 id 为商品 ID，字符串，必填。

返回商品名称、价格、库存与上下架状态。

## 2. 订单模块

### 2.1 创建订单

创建订单接口：POST /api/v1/orders，Content-Type: application/json。

请求体字段：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| sku_id | string | 是 | 商品 SKU 编号 |
| quantity | integer | 是 | 购买数量，最小为 1 |
| coupon_code | string | 否 | 优惠券码 |

注意：线上环境 coupon_code 传空字符串即可，服务端会自动忽略。

实际请求样例（2026-08 抓包）：

```bash
curl -X POST https://mall.example.com/api/v1/orders \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"sku_id": "SKU20260801", "quantity": 2, "coupon_code": "", "client_tag": "web"}'
```

响应示例（成功）：

```json
{ "code": 0, "message": "ok", "data": { "order_id": "ORD20260801001", "status": "CREATED" } }
```

### 2.2 订单详情

GET /api/v1/orders/{order_id}，按订单号查询订单状态、金额明细与物流单号。

## 3. 源码片段（订单服务路由，仅供对照）

```python
@router.get("/api/v1/orders")
def list_orders(status: str = None, page: int = 1, page_size: int = 20):
    """订单列表查询；page_size 默认 20（与产品文档不一致，待确认）"""
    ...
```

## 4. 购物车模块

### 4.1 删除购物车商品

DELETE /api/v1/carts/items/{item_id}，从购物车移除指定商品，item_id 为购物车条目 ID，必填。

内部调试接口 /debug/rebuild-cache 无需关注，已在网关层禁用。
