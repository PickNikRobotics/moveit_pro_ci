.[]
| select(
    (.fork == false)
    and (.archived == false)
    and ((.license == null) or (.license.spdx_id == "NOASSERTION"))
  )
| .full_name
