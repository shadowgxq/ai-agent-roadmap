from dataclasses import dataclass


@dataclass
class Stock:
    sku: str
    on_hand: int
    reserved: int = 0

    @property
    def available(self) -> int:
        return self.on_hand - self.reserved
