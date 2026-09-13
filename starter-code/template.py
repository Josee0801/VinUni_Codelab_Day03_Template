"""
Lab #3: Baseline Chatbot vs ReAct Agent
Học viên hoàn thiện các mục TODO để hoàn thành bài lab.
"""

import json
import re
from tools import TOOL_DEFINITIONS, TOOL_MAP, get_flight_info, get_weather_forecast

SYSTEM_PROMPT = """Bạn là một ReAct Agent thông minh hỗ trợ khách hàng Vingroup.
Bạn chỉ sử dụng các công cụ sau:
{tools}

Quy trình trả lời bắt buộc:
Thought: <Suy nghĩ bước tiếp theo>
Action: {{"name": "<tên tool>", "args": {{<tham số>}}}}
Observation: <Kết quả từ tool>
... (Lặp lại cho tới khi có đủ dữ liệu)
Final Answer: <Câu trả lời hoàn chỉnh cho khách hàng>
"""

class ChatbotBaseline:
    """Baseline LLM Chatbot (Không sử dụng ReAct Loop hay Tools)"""
    def query(self, user_input: str) -> dict:
        return {
            "status": "success",
            "answer": f"[Chatbot Baseline] Trả lời cho: {user_input}",
            "tool_calls": [],
        }

class ReActAgent:
    """ReAct Agent có sử dụng Thought-Action-Observation Loop"""
    def __init__(self, max_iterations: int = 5):
        self.max_iterations = max_iterations
        self.trace = []

    @staticmethod
    def _extract_flight_args(user_input: str):
        match = re.search(
            r"\b([A-Z]{3})\b\s+(?:đi|den|đến|to)\s+\b([A-Z]{3})\b",
            user_input,
            re.IGNORECASE,
        )
        if not match:
            return None
        price_match = re.search(
            r"(?:dưới|duoi|tối đa|toi da|under|below)\s*([\d,.]+)\s*(?:triệu|trieu|million|m)?",
            user_input,
            re.IGNORECASE,
        )
        max_price = 5000000
        if price_match:
            raw_amount = price_match.group(1)
            amount = float(raw_amount.replace(",", "."))
            match_text = price_match.group(0).lower()
            if any(unit in match_text for unit in ("triệu", "trieu", "million")):
                max_price = int(amount * 1000000)
            else:
                max_price = int(amount)
        return {
            "origin": match.group(1).upper(),
            "destination": match.group(2).upper(),
            "max_price": max_price,
        }

    @staticmethod
    def _extract_weather_code(user_input: str):
        code_matches = re.findall(r"\b(SGN|HAN|DAD)\b", user_input, re.IGNORECASE)
        if code_matches:
            return code_matches[-1].upper()
        city_codes = {"đà nẵng": "DAD", "da nang": "DAD", "hà nội": "HAN", "ha noi": "HAN"}
        lowered = user_input.lower()
        return next((code for city, code in city_codes.items() if city in lowered), None)

    @staticmethod
    def _format_flights(flights):
        if not flights:
            return "Không tìm thấy chuyến bay phù hợp."
        details = [
            f"{flight['flight_number']} ({flight['airline']}, {flight['price_vnd']:,} VND, {flight['departure_time']})"
            for flight in flights
        ]
        return "Các chuyến bay phù hợp: " + "; ".join(details) + "."

    @staticmethod
    def _format_weather(weather):
        if "error" in weather:
            return weather["error"]
        return (
            f"Thời tiết tại {weather['city']}: {weather['temperature_c']}°C, "
            f"{weather['condition']}. {weather['recommendation']}"
        )

    def _record_tool_step(self, tool_name, args):
        tool = TOOL_MAP.get(tool_name.strip().lower())
        observation = {"error": f"Unknown tool: {tool_name}"}
        if tool:
            try:
                observation = tool(**args)
            except (TypeError, ValueError) as error:
                observation = {"error": str(error)}
        self.trace.append({
            "thought": f"Gọi công cụ {tool_name} để lấy dữ liệu cần thiết.",
            "action": {"name": tool_name, "args": args},
            "observation": observation,
        })
        return observation

    def run(self, user_input: str) -> dict:
        self.trace = []
        flight_args = self._extract_flight_args(user_input)
        weather_code = self._extract_weather_code(user_input)
        lowered_input = user_input.lower()
        wants_flight = flight_args is not None and any(
            word in lowered_input for word in ("bay", "vé", "chuyến")
        )
        wants_weather = weather_code is not None and any(
            word in lowered_input for word in ("thời tiết", "weather", "mặc", "nhiệt độ")
        )

        if not wants_flight and not wants_weather:
            answer = (
                "Chính sách đổi trả vé máy bay Vinpearl phụ thuộc vào điều kiện của từng hạng vé. "
                "Vui lòng kiểm tra điều kiện vé hoặc liên hệ bộ phận hỗ trợ Vinpearl."
            )
            self.trace.append({"thought": "Đây là câu hỏi FAQ, không cần gọi tool.", "answer": answer})
            return {"status": "completed", "iterations": 1, "answer": answer, "trace": self.trace}

        flight_result = None
        weather_result = None
        if wants_flight and len(self.trace) < self.max_iterations:
            flight_result = self._record_tool_step("get_flight_info", flight_args)
        if wants_weather and len(self.trace) < self.max_iterations:
            weather_result = self._record_tool_step(
                "get_weather_forecast", {"city_code": weather_code}
            )

        if len(self.trace) >= self.max_iterations and (wants_flight and wants_weather):
            return {
                "status": "max_iterations_reached",
                "iterations": len(self.trace),
                "answer": "Không thể hoàn thành trong số bước tối đa.",
                "trace": self.trace,
            }

        answer_parts = []
        if wants_flight:
            answer_parts.append(self._format_flights(flight_result or []))
        if wants_weather:
            answer_parts.append(self._format_weather(weather_result or {"error": "Không có dữ liệu thời tiết."}))
        answer = " ".join(answer_parts)
        if wants_flight and wants_weather and len(self.trace) < self.max_iterations:
            self.trace.append({"thought": "Đã đủ dữ liệu, tổng hợp câu trả lời.", "answer": answer})
        return {"status": "completed", "iterations": len(self.trace), "answer": answer, "trace": self.trace}

def main():
    user_query = "Tìm cho tôi chuyến bay từ HAN đi SGN dưới 2 triệu, rồi cho biết thời tiết SGN nên mặc gì?"
    
    print("=== RUNNING CHATBOT BASELINE ===")
    chatbot = ChatbotBaseline()
    print(chatbot.query(user_query))
    
    print("\n=== RUNNING REACT AGENT ===")
    agent = ReActAgent(max_iterations=5)
    result = agent.run(user_query)
    print("Result:", result)
    print("Trace Log:", json.dumps(agent.trace, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()