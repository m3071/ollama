from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OCRBaseModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class DocumentMainInfo(OCRBaseModel):
    document_type: str | None = Field(default=None, alias="ประเภทเอกสาร")
    document_number: str | None = Field(default=None, alias="เลขที่เอกสาร")
    date: str | None = Field(default=None, alias="วันที่")
    time: str | None = Field(default=None, alias="เวลา")
    due_date: str | None = Field(default=None, alias="วันที่ครบกำหนด")
    reference_number: str | None = Field(default=None, alias="เลขอ้างอิง")


class SellerInfo(OCRBaseModel):
    business_name: str | None = Field(default=None, alias="ชื่อบริษัทหรือร้านค้า")
    branch: str | None = Field(default=None, alias="สาขา")
    tax_id: str | None = Field(default=None, alias="เลขประจำตัวผู้เสียภาษี")
    address: str | None = Field(default=None, alias="ที่อยู่")
    phone_number: str | None = Field(default=None, alias="เบอร์โทรศัพท์")


class BuyerInfo(OCRBaseModel):
    customer_name: str | None = Field(default=None, alias="ชื่อลูกค้า")
    tax_id: str | None = Field(default=None, alias="เลขประจำตัวผู้เสียภาษี")
    address: str | None = Field(default=None, alias="ที่อยู่")
    phone_number: str | None = Field(default=None, alias="เบอร์โทรศัพท์")
    member_id: str | None = Field(default=None, alias="รหัสสมาชิก")
    vehicle_registration: str | None = Field(default=None, alias="ทะเบียนรถ")


class LineItem(OCRBaseModel):
    order: str | None = Field(default=None, alias="ลำดับ")
    name: str | None = Field(default=None, alias="ชื่อสินค้า")
    extra_details: str | None = Field(default=None, alias="รายละเอียดเพิ่มเติม")
    quantity: float | None = Field(default=None, alias="จำนวน")
    unit: str | None = Field(default=None, alias="หน่วยนับ")
    unit_price: float | None = Field(default=None, alias="ราคาต่อหน่วย")
    line_discount: float | None = Field(default=None, alias="ส่วนลดต่อรายการ")
    line_total: float | None = Field(default=None, alias="ราคารวมรายการ")


class AmountSummary(OCRBaseModel):
    subtotal: float | None = Field(default=None, alias="รวมเป็นเงิน")
    bill_discount: float | None = Field(default=None, alias="ส่วนลดท้ายบิล")
    before_tax: float | None = Field(default=None, alias="มูลค่าก่อนภาษี")
    vat_amount: float | None = Field(default=None, alias="ภาษีมูลค่าเพิ่ม")
    non_vatable_amount: float | None = Field(default=None, alias="มูลค่ายกเว้นภาษี")
    net_total: float | None = Field(default=None, alias="ยอดสุทธิ")


class PaymentInfo(OCRBaseModel):
    payment_method: str | None = Field(default=None, alias="ช่องทางการชำระเงิน")
    amount_received: float | None = Field(default=None, alias="จำนวนเงินที่รับมา")
    change_amount: float | None = Field(default=None, alias="เงินทอน")


class OtherInfo(OCRBaseModel):
    cashier: str | None = Field(default=None, alias="พนักงานรับเงิน")
    queue_number: str | None = Field(default=None, alias="คิวที่")
    notes: str | None = Field(default=None, alias="หมายเหตุ")


class StructuredDocumentResult(OCRBaseModel):
    main_info: DocumentMainInfo = Field(default_factory=DocumentMainInfo, alias="ข้อมูลหลักของเอกสาร")
    seller_info: SellerInfo = Field(default_factory=SellerInfo, alias="ข้อมูลผู้ขาย")
    buyer_info: BuyerInfo = Field(default_factory=BuyerInfo, alias="ข้อมูลผู้ซื้อ")
    items: list[LineItem] = Field(default_factory=list, alias="รายการสินค้า")
    amount_summary: AmountSummary = Field(default_factory=AmountSummary, alias="สรุปยอดเงิน")
    payment_info: PaymentInfo = Field(default_factory=PaymentInfo, alias="ข้อมูลการชำระเงิน")
    other_info: OtherInfo = Field(default_factory=OtherInfo, alias="ข้อมูลอื่นๆ")


class OCRResultEnvelope(BaseModel):
    result: StructuredDocumentResult

    @model_validator(mode="before")
    @classmethod
    def validate_payload(cls, value: Any) -> Any:
        if isinstance(value, dict) and "result" not in value:
            return {"result": value}
        return value


class OCRSpaceParsedResult(BaseModel):
    TextOverlay: dict[str, Any] | None = None
    FileParseExitCode: int
    ParsedText: str | None = None
    StructuredData: dict[str, Any] | None = None
    ErrorMessage: str = ""
    ErrorDetails: str = ""
    # Orientation detection is not implemented in this self-hosted build yet.
    TextOrientation: str = "0"


class OCRSpaceResponse(BaseModel):
    ParsedResults: list[OCRSpaceParsedResult]
    OCRExitCode: int
    IsErroredOnProcessing: bool
    ErrorMessage: str | None = None
    ErrorDetails: str | None = None
    ProcessingTimeInMilliseconds: str
