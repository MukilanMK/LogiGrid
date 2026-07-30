import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime

DATABASE_URL = "mongodb://localhost:27017/"
DB_NAME = "profit_analytics"

async def seed_data():
    client = AsyncIOMotorClient(DATABASE_URL)
    db = client[DB_NAME]
    
    # Products Data
    products_data = [
      {
        "_id": "11111111-1111-1111-1111-000000000001",
        "name": "Wireless Noise-Cancelling Headphones",
        "category": "Audio",
        "hsn_code": "8518",
        "tax_rate": 18.00,
        "cost_price": 120.00,
        "selling_price": 250.00
      },
      {
        "_id": "11111111-1111-1111-1111-000000000002",
        "name": "Mechanical Keyboard Pro",
        "category": "Accessories",
        "hsn_code": "8471",
        "tax_rate": 18.00,
        "cost_price": 55.00,
        "selling_price": 130.00
      },
      {
        "_id": "11111111-1111-1111-1111-000000000003",
        "name": "Ergonomic Office Chair",
        "category": "Furniture",
        "hsn_code": "9403",
        "tax_rate": 18.00,
        "cost_price": 150.00,
        "selling_price": 350.00
      },
      {
        "_id": "11111111-1111-1111-1111-000000000004",
        "name": "USB-C Fast Charger",
        "category": "Accessories",
        "hsn_code": "8504",
        "tax_rate": 18.00,
        "cost_price": 8.00,
        "selling_price": 25.00
      }
    ]

    # Sales Invoices Data
    sales_data = [
      {
        "_id": "22222222-2222-2222-2222-000000000001",
        "timestamp": datetime.strptime("2026-07-25T10:15:00Z", "%Y-%m-%dT%H:%M:%SZ"),
        "customer_gstin": None,
        "taxable_value": 380.00,
        "total_tax": 68.40,
        "total_amount": 448.40,
        "line_items": [
          {
            "line_item_id": "33333333-3333-3333-3333-000000000001",
            "product_id": "11111111-1111-1111-1111-000000000001",
            "quantity": 1,
            "unit_margin": 130.00
          },
          {
            "line_item_id": "33333333-3333-3333-3333-000000000002",
            "product_id": "11111111-1111-1111-1111-000000000002",
            "quantity": 1,
            "unit_margin": 75.00
          }
        ]
      },
      {
        "_id": "22222222-2222-2222-2222-000000000002",
        "timestamp": datetime.strptime("2026-07-26T14:30:00Z", "%Y-%m-%dT%H:%M:%SZ"),
        "customer_gstin": "27AAPCU3391M1Z5",
        "taxable_value": 700.00,
        "total_tax": 126.00,
        "total_amount": 826.00,
        "line_items": [
          {
            "line_item_id": "33333333-3333-3333-3333-000000000003",
            "product_id": "11111111-1111-1111-1111-000000000003",
            "quantity": 2,
            "unit_margin": 200.00
          }
        ]
      },
      {
        "_id": "22222222-2222-2222-2222-000000000003",
        "timestamp": datetime.strptime("2026-07-27T09:45:00Z", "%Y-%m-%dT%H:%M:%SZ"),
        "customer_gstin": None,
        "taxable_value": 125.00,
        "total_tax": 22.50,
        "total_amount": 147.50,
        "line_items": [
          {
            "line_item_id": "33333333-3333-3333-3333-000000000004",
            "product_id": "11111111-1111-1111-1111-000000000004",
            "quantity": 5,
            "unit_margin": 17.00
          }
        ]
      }
    ]

    try:
        # Clear collections if they exist to start fresh
        await db.products.delete_many({})
        await db.sales_invoices.delete_many({})
        
        await db.products.insert_many(products_data)
        await db.sales_invoices.insert_many(sales_data)
        print("Database seeded successfully with MongoDB collections.")
    except Exception as e:
        print(f"Error seeding database: {e}")
    finally:
        client.close()

if __name__ == "__main__":
    asyncio.run(seed_data())
