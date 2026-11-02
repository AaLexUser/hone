import type { Seat } from './model'
import { monogram, seatLabel, shortModel } from './derive'

const TONE = {
  review: 'bg-rev/12 text-rev ring-rev/25',
  propose: 'bg-pro/12 text-pro ring-pro/25',
} as const

/** A seat as a small colored monogram (R1, P2, J); the stage hue matches its box on the graph. */
export function SeatChip({ seat, dim = false }: { seat: Seat; dim?: boolean }) {
  return (
    <span
      title={`${seatLabel(seat)} · ${shortModel(seat.model)}`}
      className={`inline-grid h-5 min-w-7 shrink-0 place-items-center rounded-[5px] px-1 font-mono text-[12px] font-semibold ring-1 ring-inset ${TONE[seat.stage]} ${
        dim ? 'opacity-50' : ''
      }`}
    >
      {monogram(seat)}
    </span>
  )
}
