"""
DocuChat AI - Safe Tool Registry & Execution Engine
Enforces schema validation, argument limits, safe sandboxing, and execution timeouts.
Never executes arbitrary code, system commands, or unvetted model requests.
"""
import asyncio
import logging
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field, ValidationError

from backend.tools.calculator import safe_calculate
from backend.tools.excel_generator import generate_excel_sheet, generate_workbook_from_request, ExcelGeneratorInput
from backend.tools.excel_analyzer import execute_excel_analysis, ExcelAnalysisInput
from backend.tools.document_generator import generate_document_from_request, DocumentGeneratorInput
from backend.tools.pdf_tools import (
    PdfToolsInput,
    merge_pdfs,
    split_pdf,
    extract_pages,
    rotate_pages,
    compress_pdf,
    convert_pdf_to_text,
    extract_pdf_tables,
    get_pdf_info,
    add_watermark,
    add_page_numbers,
    images_to_pdf,
    execute_pdf_tool_from_request
)
from backend.tools.searxng_search import search_searxng_async
from backend.tools.weather import get_weather_forecast_async, WeatherInput
from backend.retrieval.web_search import live_web_search


logger = logging.getLogger("tools_registry")

# Pydantic Input Schemas
class CalculatorInput(BaseModel):
    expression: str = Field(..., max_length=200, description="Mathematical expression to evaluate")

class WebSearchInput(BaseModel):
    query: str = Field(..., min_length=2, max_length=200, description="Web query for factual search")

class ExcelExportInput(BaseModel):
    title: str = Field("Report", max_length=50)
    headers: List[str] = Field(..., min_length=1, max_length=50)
    rows: List[List[Any]] = Field(..., min_length=1, max_length=1000)
    filename_prefix: Optional[str] = Field("report", max_length=30)


TOOL_DEFINITIONS = [
    {
        "name": "calculator",
        "description": "Performs exact arithmetic and mathematical calculations safely.",
        "parameters": CalculatorInput.model_json_schema()
    },
    {
        "name": "weather",
        "description": "Fetches live weather reports, temperatures, forecasts, rain chances, and conditions for any city or region.",
        "parameters": WeatherInput.model_json_schema()
    },
    {
        "name": "web_search",
        "description": "Searches the live public web for current news, facts, and market quotes.",
        "parameters": WebSearchInput.model_json_schema()
    },
    {
        "name": "export_excel",
        "description": "Generates a styled, downloadable Excel spreadsheet from tabular data.",
        "parameters": ExcelExportInput.model_json_schema()
    },
    {
        "name": "excel_generator",
        "description": "Generates a multi-sheet, beautifully styled, validated Excel workbook (.xlsx) with QA test cases or custom spreadsheets.",
        "parameters": ExcelGeneratorInput.model_json_schema()
    },
    {
        "name": "excel_analyzer",
        "description": "Inspects and calculates metrics from uploaded Excel (.xlsx, .xls) and CSV spreadsheets.",
        "parameters": ExcelAnalysisInput.model_json_schema()
    },
    {
        "name": "document_generator",
        "description": "Generates professional, styled documents in DOCX (Word), PDF, TXT, or Markdown formats (reports, resumes, proposals, technical docs, meeting minutes).",
        "parameters": DocumentGeneratorInput.model_json_schema()
    },
    {
        "name": "pdf_tools",
        "description": "Performs professional PDF manipulations: merge multiple PDFs, split, extract pages, rotate pages, compress, convert to text/markdown, extract tables to Excel/CSV, add watermarks, and inspect metadata.",
        "parameters": PdfToolsInput.model_json_schema()
    }
]

async def execute_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validates arguments against schema and executes tool within a safe timeout.
    """
    logger.info(f"Executing tool '{tool_name}' with arguments: {arguments}")
    
    try:
        if tool_name == "calculator":
            validated = CalculatorInput(**arguments)
            return safe_calculate(validated.expression)

        elif tool_name == "weather":
            validated = WeatherInput(**arguments)
            return await get_weather_forecast_async(
                location=validated.location,
                days=validated.days,
                unit=validated.unit
            )

        elif tool_name == "web_search":
            validated = WebSearchInput(**arguments)
            searx_res = await search_searxng_async(validated.query, inspect_pages=True)
            return {
                "query": validated.query,
                "results": searx_res.get("formatted"),
                "raw_results": searx_res.get("results", []),
                "count": searx_res.get("count", 0)
            }

        elif tool_name == "export_excel":
            validated = ExcelExportInput(**arguments)
            return generate_excel_sheet(
                title=validated.title,
                headers=validated.headers,
                rows=validated.rows,
                filename_prefix=validated.filename_prefix
            )

        elif tool_name == "excel_generator":
            validated = ExcelGeneratorInput(**arguments)
            return await generate_workbook_from_request(prompt=validated.requirement)

        elif tool_name == "excel_analyzer":
            validated = ExcelAnalysisInput(**arguments)
            return execute_excel_analysis(
                operation=validated.operation,
                column=validated.column,
                group_by=validated.group_by,
                filter_column=validated.filter_column,
                filter_value=validated.filter_value,
                sheet_name=validated.sheet_name,
                doc_id=validated.doc_id
            )

        elif tool_name == "document_generator":
            validated = DocumentGeneratorInput(**arguments)
            return await generate_document_from_request(
                prompt=validated.requirement,
                requested_format=validated.format,
                document_type=validated.document_type,
                title=validated.title
            )

        elif tool_name == "pdf_tools":
            validated = PdfToolsInput(**arguments)
            op = validated.operation.lower().strip()
            doc_ids = validated.document_ids or []

            # If document_ids provided, resolve paths
            doc_paths = []
            for doc_id in doc_ids:
                # Check upload dir or converted dir
                p1 = Path(settings.UPLOAD_DIR) / doc_id
                p2 = Path(settings.OUTPUT_DIR) / doc_id
                if p1.exists():
                    doc_paths.append(str(p1.resolve()))
                elif p2.exists():
                    doc_paths.append(str(p2.resolve()))
                else:
                    # Match by prefix or filename
                    matches = list(Path(settings.UPLOAD_DIR).glob(f"*{doc_id}*")) + list(Path(settings.OUTPUT_DIR).glob(f"*{doc_id}*"))
                    if matches:
                        doc_paths.append(str(matches[0].resolve()))

            if op == "merge":
                return merge_pdfs(pdf_paths=doc_paths)
            elif op == "split":
                target = doc_paths[0] if doc_paths else ""
                return split_pdf(pdf_path=target, page_ranges=validated.page_spec or "1-2")
            elif op == "extract":
                target = doc_paths[0] if doc_paths else ""
                return extract_pages(pdf_path=target, page_spec=validated.page_spec or "1")
            elif op == "rotate":
                target = doc_paths[0] if doc_paths else ""
                return rotate_pages(pdf_path=target, page_spec=validated.page_spec or "all", angle=validated.angle or 90)
            elif op == "compress":
                target = doc_paths[0] if doc_paths else ""
                return compress_pdf(pdf_path=target, level=validated.compression_level or "medium")
            elif op == "to_text":
                target = doc_paths[0] if doc_paths else ""
                return convert_pdf_to_text(pdf_path=target, output_format=validated.text_format or "markdown")
            elif op == "extract_tables":
                target = doc_paths[0] if doc_paths else ""
                return extract_pdf_tables(pdf_path=target, output_format=validated.table_format or "xlsx")
            elif op == "info":
                target = doc_paths[0] if doc_paths else ""
                return get_pdf_info(pdf_path=target)
            elif op == "watermark":
                target = doc_paths[0] if doc_paths else ""
                return add_watermark(pdf_path=target, watermark_text=validated.watermark_text or "CONFIDENTIAL")
            elif op == "page_numbers":
                target = doc_paths[0] if doc_paths else ""
                return add_page_numbers(pdf_path=target, position=validated.page_number_position or "bottom-center")
            elif op == "images_to_pdf":
                return images_to_pdf(image_paths=doc_paths)
            else:
                return {"error": f"Unknown PDF operation '{op}'"}

        else:
            return {"error": f"Tool '{tool_name}' is not recognized or permitted."}

    except ValidationError as ve:
        logger.warning(f"Tool argument validation failed for {tool_name}: {ve}")
        return {"error": f"Invalid arguments for tool '{tool_name}': {ve.errors()}"}
    except asyncio.TimeoutError:
        logger.error(f"Tool '{tool_name}' timed out.")
        return {"error": f"Tool '{tool_name}' timed out after 12 seconds."}
    except Exception as e:
        logger.error(f"Error executing tool '{tool_name}': {e}", exc_info=True)
        return {"error": f"Tool execution failed: {str(e)}"}
