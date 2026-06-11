from abc import ABC, abstractmethod


class BuyStrategy(ABC):
    """매수 후보 선정 전략 인터페이스"""

    @property
    def display_name(self) -> str:
        """대시보드 그룹 헤더 등에 쓰일 한글 표시명. 기본은 클래스명."""
        return type(self).__name__

    @abstractmethod
    def find_candidates(self) -> list[dict]:
        """매수 후보 종목 목록 반환.

        반환 형식 (각 항목):
            {"종목코드": str, "종목명": str, "현재가": float, "거래량": int, ...}
        """
        ...


class SellStrategy(ABC):
    """매도 판단 전략 인터페이스.

    전략별 내부 상태(최고가, 지표 누적 등)는 구현체가 직접 소유하고 영속화한다.
    트레이더는 범용 훅(observe/on_buy/should_sell)만 호출한다.
    """

    @property
    def display_name(self) -> str:
        """대시보드 selectbox 등에 쓰일 한글 표시명. 기본은 클래스명."""
        return type(self).__name__

    @abstractmethod
    def should_sell(self, code: str, current_price: float) -> tuple[bool, str]:
        """매도 조건 판단.

        Returns:
            (매도여부, 사유 문자열)
        """
        ...

    def observe(self, code: str, current_price: float) -> None:
        """매 주기마다 현재가를 받아 내부 상태를 갱신. 기본 no-op."""

    def on_buy(self, code: str, buy_price: float, reset: bool = False) -> None:
        """신규 매수 감지 시 초기 상태 세팅. 기본 no-op.

        Args:
            reset: True 면 해당 종목의 기존 내부 상태(예: 최고가)를 무시하고
                매수가 기준으로 강제 재설정한다. 외부 툴 매수/매도로 트레이더가
                인지하지 못한 사이 orphan 상태가 남았을 때, 신규 편입 감지 경로가
                이를 매수가로 덮어 stale 한 이전 구간 상태가 새 보유에 새어드는 것을
                막기 위함이다. 시작 시 priming 처럼 영속 상태를 보존해야 하는
                경로는 False(기본)로 호출해 누적된 정상 상태를 유지한다.
        """

    def on_sell(self, code: str) -> None:
        """매도(보유 청산) 감지 시 종목별 내부 상태 정리. 기본 no-op.

        재매수 시 이전 보유 구간의 상태(예: 최고가)가 남아 새 매수가 기준이
        오염되지 않도록, 구현체가 종목별 상태를 폐기할 수 있게 한다.
        """

    def reconcile(self, held_codes: set[str]) -> None:
        """현재 실제 보유 종목과 내부 상태를 동기화. 기본 no-op.

        트레이더가 내려가 있는 동안 외부 툴로 매도된 종목은 on_sell 정리가
        누락되어 종목별 상태(예: 최고가)가 orphan 으로 남는다. 시작 시 실제 보유
        종목 집합을 받아, 보유하지 않는 종목의 상태를 폐기하도록 구현체가 override 한다.
        """

    def load(self) -> None:
        """프로그램 시작 시 영속 상태 복원. 기본 no-op."""

    def save(self) -> None:
        """내부 상태 저장. 기본 no-op."""

    def describe(self, code: str, current_price: float) -> str:
        """로그/대시보드 표시용 상태 요약 문자열. 기본: 빈 문자열."""
        return ""
