import type { CaseDetail } from '../api'
import { SemanticContracts } from './SemanticContracts'
import { SemanticGraph } from './SemanticGraph'
import { contextDate } from './semanticPresentation'

function money(value: number | null | undefined) {
  return value == null ? 'not available' : value.toLocaleString('en-SG', { maximumFractionDigits: 0 })
}

export function SemanticExplorer({ detail }: { customerId: string; alertId: string; detail: CaseDetail }) {
  const account = detail.account_id || 'the selected account'
  return <div className="space-y-4 text-xs text-ink">
    <section className="rounded-lg border border-surface-3 bg-white p-5">
      <p className="font-semibold text-accent">01 / ACCOUNT INTERPRETATION</p>
      <h2 className="mt-1 text-xl font-bold">What this account data says</h2>
      <p className="mt-3 leading-6">
        <strong>{detail.customer_name}</strong> holds account <strong>{account}</strong>. The customer profile records
        expected monthly turnover of <strong>{money(detail.expected_monthly_turnover)}</strong> and a
        <strong> {detail.customer_kyc_rating || 'not recorded'}</strong> KYC risk rating.
      </p>
      <p className="mt-2 leading-6">
        Recorded outbound activity over 30 days is <strong>{money(detail.observed_outflow_30d)}</strong>.
        This is observed account activity; expected turnover is a customer declaration.
      </p>
      <p className="mt-2 leading-6">
        The <strong>{(detail.risk_score * 100).toFixed(1)}%</strong> priority score ranks this account for review.
        It is not a probability of wrongdoing.
      </p>
      <p className="mt-3 text-ink-muted">Account scope: {account} · data cutoff: {contextDate(detail.data_cutoff_at)}</p>
    </section>

    <section className="rounded-lg border border-surface-3 bg-white p-5">
      <p className="font-semibold text-accent">02 / OSSIE MODEL & LINEAGE</p>
      <h2 className="mt-1 text-xl font-bold">How the data connects</h2>
      <p className="mt-2 text-ink-muted">Select a node to see its business meaning, source and declared relationship to other data.</p>
      <div className="mt-4"><SemanticGraph detail={detail} /></div>
    </section>

    <section className="rounded-lg border border-surface-3 bg-white p-5">
      <p className="font-semibold text-accent">03 / ORIGINAL FILES</p>
      <h2 className="mt-1 text-xl font-bold">Ossie source files</h2>
      <p className="mt-2 mb-4 text-ink-muted">Open the original model only when you need the full definitions.</p>
      <SemanticContracts />
    </section>
  </div>
}
