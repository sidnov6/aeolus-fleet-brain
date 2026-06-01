# Maintenance Scheduling Policy (economics & safety)

Choose the maintenance window that minimises total expected cost:
LostRevenue (price x expected generation during downtime) + RiskCost
(failure probability x unplanned-failure cost). Constraints: a skilled crew must
be available; wind inside the window must stay within the safe-climb envelope
(<= 12 m/s); no firm grid dispatch commitment may be breached.

Because SCADA prognosis can flag degradation weeks ahead, prefer a low-generation,
low-price, low-wind window over an immediate "fix-now" intervention. Always
prefer a planned intervention over running to an unplanned failure: a planned
job costs roughly a quarter of the unplanned event plus its extended downtime.
