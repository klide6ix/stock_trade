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

    @abstractmethod
    def should_sell(self, code: str, current_price: float) -> tuple[bool, str]:
        """매도 조건 판단.

        Returns:
            (매도여부, 사유 문자열)
        """
        ...

    def observe(self, code: str, current_price: float) -> None:
        """매 주기마다 현재가를 받아 내부 상태를 갱신. 기본 no-op."""

    def on_buy(self, code: str, buy_price: float) -> None:
        """신규 매수 감지 시 초기 상태 세팅. 기본 no-op."""

    def load(self) -> None:
        """프로그램 시작 시 영속 상태 복원. 기본 no-op."""

    def save(self) -> None:
        """내부 상태 저장. 기본 no-op."""

    def describe(self, code: str, current_price: float) -> str:
        """로그/대시보드 표시용 상태 요약 문자열. 기본: 빈 문자열."""
        return ""
