import urlparse
import os, sys, re
import math
from flask import Flask, request, Response, jsonify, abort, json, make_response
from msc_apps import *
from decimal import Decimal
from blockchain_utils import *
from stats_service import raw_revision

app = Flask(__name__)
app.debug = True

@app.route('/estimatefee/<addr>', methods=['GET','POST'])
def estimatefees(addr):
    try:
      address = str(re.sub(r'\W+', '', addr ) ) #check alphanumeric
    except ValueError:
      abort(make_response('This endpoint only consumes valid input', 400))

    try:
      amountBTC=int( Decimal(request.form['amountBTC']) * Decimal(1e8))
    except:
      amountBTC=0

    #get dynamic fee rates from db
    try:
      fees=getfeesRaw()
    except Exception as e:
      print "Fee lookup failed, falling back"
      print e
      fees={"unit": "Satoshi/kB", "faster": 275000, "fast": 245000, "normal": 215000}

    #initial miner fee estimate
    mfee=25000

    #class B tx: output base cost
    cbb=4410

    #Class C tx: output base cost
    ccb=546

    ins=1
    outs=2

    amount=ccb+mfee+amountBTC

    balance=bc_getbalance(address)
    if 'bal' in balance and balance['bal']>0:
      unspent=bc_getutxo(addr,amount)
      if 'utxos' in unspent:
        ins=len(unspent['utxos'])
        if unspent['avail'] == amount:
          outs=1

    #ins + outs + header + opreturn
    size=ins*180 + outs*34 + 10 + 80
    tsize=math.ceil((size+180)*1.05)

    faster = '%.8f' % ( Decimal(int((size * fees['faster'])/1000)) / Decimal(1e8) )
    fast = '%.8f' % ( Decimal(int((size * fees['fast'])/1000)) / Decimal(1e8) )
    normal = '%.8f' % ( Decimal(int((size * fees['normal'])/1000)) / Decimal(1e8) )

    tfaster = '%.8f' % ( Decimal(int((tsize * fees['faster'])/1000)) / Decimal(1e8) )
    tfast = '%.8f' % ( Decimal(int((tsize * fees['fast'])/1000)) / Decimal(1e8) )
    tnormal = '%.8f' % ( Decimal(int((tsize * fees['normal'])/1000)) / Decimal(1e8) )

    ret={"address":addr,
         "class_c":{"faster": faster, "fast": fast, "normal": normal, "estimates":{"size":size, "ins":ins, "outs":outs} },
         "topup_c":{"faster": tfaster, "fast": tfast, "normal": tnormal, "estimates":{"size":tsize, "ins":ins+1, "outs":outs} }
        }
    return jsonify(ret)

@app.route('/fees')
def getfees():
    return jsonify(getfeesRaw())

def getfeesRaw():
    fee={}
    ROWS=dbSelect("select value from settings where key='feeEstimates'")
    print ROWS
    if len(ROWS) > 0:
      fee=json.loads(ROWS[0][0])

    fee['unit']='Satoshi/kB'
    return fee

@app.route('/estimatetxcost', methods=['POST'])
def estimatetxcost():
    try:
        address = str(re.sub(r'\W+', '', request.form['address'] ) ) #check alphanumeric
        type = int(re.sub(r'\d', '', request.form['txtype'] ) )
    except ValueError:
        abort(make_response('This endpoint only consumes valid input', 400))


@app.route('/address', methods=['POST'])
def getaddresshist():
    try:
        address = str(re.sub(r'\W+', '', request.form['addr'] ) ) #check alphanumeric
    except ValueError:
        abort(make_response('This endpoint only consumes valid input', 400))

    try:
      page=int(request.form['page'])
    except:
      page=0
    return jsonify(getaddresshistraw(address,page))


def getaddresshistraw(address,page):
    offset=page*10
    ROWS=dbSelect("select txj.txdata from txjson txj, addressesintxs atx where atx.txdbserialnum=txj.txdbserialnum and atx.address=%s order by txj.txdbserialnum desc limit 50 offset %s",(address,offset))
    pcount=getaddresstxcount(address)
    response = { 'address': address, 'transactions': ROWS , 'pages': pcount}

    return response


def getaddress_OLD():
    try:
        address = str(re.sub(r'\W+', '', request.form['addr'] ) ) #check alphanumeric
    except ValueError:
        abort(make_response('This endpoint only consumes valid input', 400))

    ROWS=dbSelect("""select t.TxHash, t.TxType, t.TxRecvTime, t.TxState,
                            atx.AddressRole, atx.BalanceAvailableCreditDebit,
                            sp.PropertyData
                      from transactions t, addressesintxs atx, smartproperties sp
                      where t.txdbserialnum = atx.txdbserialnum and sp.PropertyID = atx.PropertyID and atx.address=%s and t.txdbserialnum >0
                      and sp.Protocol != 'Fiat'
                      order by t.txdbserialnum DESC""", [address])

    transactions = []

    if len(ROWS) > 0:
      for txrow in ROWS:
        transaction = {}

        transaction['hash'] = txrow[0]
        transaction['type'] = txrow[1]
        transaction['time'] = txrow[2]
        transaction['state'] = txrow[3]
        transaction['role'] = txrow[4]
        transaction['amount'] = str(txrow[5])
        transaction['currency'] = txrow[6]

        transactions.append(transaction)

    response = { 'address': address, 'transactions': transactions }

    return jsonify(response)

def getpagecounttxjson(limit=10):
  #todo add caching
  ROWS=dbSelect("select count(txdbserialnum) from txjson;")
  return (int(ROWS[0][0])/limit)

def getaddresstxcount(address,limit=10):
  ROWS=dbSelect("select count(txdbserialnum) from addressesintxs where address=%s;",[address])
  return (int(ROWS[0][0])/limit)


@app.route('/general/')
def getrecenttx():
  return getrecenttxpages()

@app.route('/general/<page>')
def getrecenttxpages(page=0):
    try:
      offset=int(page)*10
    except:
      offset=0
    ROWS=dbSelect("select txdata from txjson txj where protocol != 'Bitcoin' order by txdbserialnum DESC offset %s limit 10;",[offset])
    rev=raw_revision()
    cblock=rev['last_block']
    response = []
    if len(ROWS) > 0:
      for data in ROWS:
        res = data[0]
        try:
          res['confirmations'] = cblock - res['block'] + 1
        except:
          pass
        response.append(res)
    pages=getpagecounttxjson()
    #return Response(json.dumps(response), mimetype="application/json")
    return jsonify({'pages':pages,'data':response})


def gettxjson(hash_id):
    try:
        transaction_ = str(re.sub(r'\W+', '', hash_id.split('.')[0] ) ) #check alphanumeric
    except ValueError:
        return {'error':'This endpoint only consumes valid input. Invalid txid'}

    ROWS=dbSelect("select txj.txdata from transactions t, txjson txj where t.txdbserialnum = txj.txdbserialnum and t.protocol != 'Bitcoin' and t.txhash=%s", [transaction_])
    rev=raw_revision()
    cblock=rev['last_block']

    if len(ROWS) < 1:
      return json.dumps([])
    try:
      txJson = json.loads(ROWS[0][0])
    except TypeError:
      txJson = ROWS[0][0]

    try:
      txJson['confirmations'] = cblock - txJson['block'] + 1
    except:
      pass
    return txJson

def getblockhash(blocknumber):
    try:
        block_ = int( blocknumber ) #check numeric
        ROWS=dbSelect("select blockhash from blocks where blocknumber=%s", [block_])
    except Exception as e:
        return {'error':'This endpoint only consumes valid input. Invalid block'}

    if len(ROWS) < 1:
      return "error: block not available."
    else:
      return ROWS[0][0]

def getblocktxjson(block):
    bhash=getblockhash(block)
    if "error" in bhash:
      return bhash

    try:
        block_ = int( block ) #check numeric
        ROWS=dbSelect("select * from transactions t, txjson txj where t.txdbserialnum = txj.txdbserialnum and t.protocol != 'Bitcoin' and t.txblocknumber=%s", [block_])
    except Exception as e:
        return {'error':'This endpoint only consumes valid input. Invalid block'}

    ret=[]
    for x in ROWS:
      try:
        txJson = json.loads(x[-1])
      except TypeError:
        txJson = x[-1]
      ret.append(txJson)

    return {"block":block_, "blockhash":bhash, "transactions": ret}

def getaddrhist(address,direction='both',page=0):
    try:
        address_ = str(re.sub(r'\W+', '', address.split('.')[0] ) ) #check alphanumeric
    except ValueError:
        return {'error':'This endpoint only consumes valid input. Invalid address'}

    try:
      offset=int(page)*50
    except:
      offset=0

    role='address'
    query="select t.txhash from transactions t, addressesintxs atx where t.txdbserialnum = atx.txdbserialnum and t.protocol != 'Bitcoin' and atx.address='"+str(address_)+"'"
    if direction=='send':
      role='sender'
      query+=" and atx.addressrole='sender'"
    elif direction=='receive':
      role="recipient"
      query+=" and atx.addressrole='recipient'"
    query+=" order by t.txdbserialnum DESC offset " +str(offset)+ " limit 50"
    ROWS=dbSelect(query)

    ret=[]
    for x in ROWS:
      ret.append(x[0])

    return {role:address_,"transactions":ret}

@app.route('/tx/<hash_id>')
def gettransaction(hash_id):
    try:
        transaction_ = str(re.sub(r'\W+', '', hash_id.split('.')[0] ) ) #check alphanumeric
    except ValueError:
        abort(make_response('This endpoint only consumes valid input', 400))

    return jsonify(gettxjson(transaction_))

def gettransaction_OLD(hash_id):
    try:
        transaction_ = str(re.sub(r'\W+', '', hash_id.split('.')[0] ) ) #check alphanumeric
    except ValueError:
        abort(make_response('This endpoint only consumes valid input', 400))

    ROWS=dbSelect("select * from transactions t, txjson txj where t.txdbserialnum = txj.txdbserialnum and t.protocol != 'Bitcoin' and t.txhash=%s", [transaction_])

    if len(ROWS) < 1:
      return json.dumps([])

    def dehexify(hex_str):
        temp_str=[]
        for let in hex_str:
            if ord(let) < 128:
                temp_str.append(let)
            else:
                temp_str.append('?')
        return ''.join(temp_str)

    try:
      txJson = json.loads(ROWS[0][-1])
    except TypeError:
      txJson = ROWS[0][-1]
    txData = ROWS[0][:-1]

    txType = ROWS[0][3]
    txValid = True if ROWS[0][7] == 'valid' else False

    #  0 - Simple send
    # 56 - Revoke Property Tokens
    # 55 - Grant Property Tokens
    # 53 - Close crowdsale
    # -1 - invalid tx
    # 21 - Metadex - TODO
    #  3 - Send to Owners - TODO

    ret = {
      "block": txData[9],
      "ecosystem": '1' if txData[5] == 'Production' else '2',
      "from_address": txJson['sendingaddress'],
      "transactionType": txData[3],
      "transactionVersion": txData[4],
      "to_address": str("(null)"),
      "confirms": txJson['confirmations'],
      "tx_hash": txData[0],
      "tx_time": (str(txJson['blocktime']) + '000') if 'blocktime' in txJson else '',
    }

    if txType not in [-22,21,25,26,27,28]: #Dex purchases don't have these fields
      ret['currencyId'] = txJson['propertyid']
      ret['currency_str'] = 'Omni' if txJson['propertyid'] == 1 else 'Test Omni' if txJson['propertyid'] == 2 else "Smart Property"
      ret['invalid'] = not txValid
      ret['amount'] = str(txJson['amount'])
      ret['formatted_amount'] = txJson['amount']
      ret['divisible'] = txJson['divisible']
      ret['fee'] = txJson['fee']
      ret['tx_type_str'] = txJson['type']

    if txType == 0 and txValid:
        ret['to_address'] = txJson['referenceaddress']

    if (txType == 50 or txType == 51 or txType == 54) and txValid:

      # 50 - Create property fixed - propertyname (getproperty), category, totaltokens, url, data, subcategory
      # 51 - Create property Variable - propertyname, (getproperty) , tokensperunit, subcategory, totaltokens, deadline,
      # category, amountraised, closedearly, propertyiddesired, maxtokens, percenttoissuer, earlybonus, active, data, url,  tokensissued, starttime
      # 54 - Create Property Manual - propertyname, (getgrants), category, totaltokens, url, [issuances], subcategory, data

      ROWS=dbSelect("select * from transactions t, smartproperties sp where t.txhash=%s and t.txdbserialnum = sp.createtxdbserialnum", [transaction_])
      try:
        mpData = json.loads(ROWS[0][-1])
      except TypeError:
        mpData = ROWS[0][-1]

      ret['previous_property_id'] = "(null)" #TODO FIXME

      ret['propertyName'] = dehexify( mpData['name'] )
      ret['propertyCategory'] = dehexify( mpData['category'] )
      ret['propertyData'] = dehexify( mpData['data'] )
      ret['propertySubcategory'] = dehexify( mpData['subcategory'] )
      ret['propertyUrl'] = dehexify( mpData['url'] )

      ret['propertyType'] = '0002' if mpData['divisible'] == True else '0001'
      ret['formatted_property_type'] = int('0002' if mpData['divisible'] == True else '0001')

      if txType == 50 or txType == 54: ret['numberOfProperties'] = str(mpData['totaltokens']);

      if txType == 51:
        ret['numberOfProperties'] = str(mpData['tokensperunit']);
        ret['currencyIdentifierDesired'] = mpData['propertyiddesired']
        ret['deadline'] = mpData['deadline']
        ret['earlybirdBonus'] = mpData['earlybonus']
        ret['percentageForIssuer'] = mpData['percenttoissuer']

      if txType == 54: ret['issuances'] = mpData['issuances']


    if (txType == 20 or txType == 22) and txValid:

      # 20 - Dex Sell - subaction, bitcoindesired, timelimit
      # 22 - Dex Accepts - referenceaddress

      if txType == 20:
        action = 'subaction' if 'subaction' in txJson else 'action'
        cancel = True if txJson[action] == 'cancel' else False

        if not cancel:
          ROWS=dbSelect("select * from transactions t, activeoffers ao, txjson txj where t.txhash=%s "
                        "and t.txdbserialnum = ao.createtxdbserialnum and t.txdbserialnum=txj.txdbserialnum", [transaction_])
          row = ROWS[0]
          try:
            mpData = json.loads(ROWS[0][-1])
          except TypeError:
            mpData = ROWS[0][-1]

          ppc = Decimal( mpData['bitcoindesired'] ) / Decimal( mpData['amount'] )
          ret['amount_available'] = str(row[12])
          ret['formatted_amount_available'] = '%.8f' % ( Decimal(row[12]) / Decimal(1e8) )
          ret['bitcoin_amount_desired'] = str(row[13])
          ret['formatted_bitcoin_amount_desired'] = '%.8f' % ( Decimal(row[13]) / Decimal(1e8) )
          ret['formatted_block_time_limit'] = str(mpData['timelimit'])
          ret['formatted_fee_required'] = str(mpData['feerequired'])
          ret['formatted_price_per_coin'] = '%.8f' % ppc
          ret['bitcoin_required'] = '%.8f' % ( Decimal( ppc ) * Decimal( mpData['amount'] ) )
          ret['subaction'] = mpData[action]

        if cancel:
          ret['formatted_block_time_limit'] = str(txJson['timelimit'])
          ret['formatted_fee_required'] = str(txJson['feerequired'])
          ret['subaction'] = txJson[action]
          ret['tx_type_str'] = 'Sell cancel'

      if txType == 22:
        ROWS=dbSelect("select * from transactions t, offeraccepts oa, txjson txj where t.txhash=%s "
                      "and t.txdbserialnum = oa.linkedtxdbserialnum and t.txdbserialnum=txj.txdbserialnum", [transaction_])
        try:
          mpData = json.loads(ROWS[0][-1])
        except TypeError:
          mpData = ROWS[0][-1]

        ret['to_address'] = mpData['referenceaddress']

    if (txType == -51 or txType -22) and txValid:

        #-51 - Crowdsale Purchase - purchasedpropertyid, referenceaddress, purchasedpropertydivisible, purchasedpropertyname, purchasedtokens, issuertokens, (getcrowdsale)
        #-22 - Dex Purchase - [ purchases ]

      if txType == -22:
        ret['purchases'] = txJson['purchases']
        ret['currencyId'] = '0'
        ret['currency_str'] = 'Bitcoin'
        ret['tx_type_str'] = 'Dex Purchase'

        payment = 0
        for each in ret['purchases']:
           payment += float(each['amountpaid'])
        ret['accomulated_payment'] = payment

      if txType == -51:
        ret['purchasepropertyid'] = txJson['purchasedpropertyid']
        ret['to_address'] = txJson['referenceaddress']
        ret['purchaedpropertydivisible'] = txJson['purchasedpropertydivisible']
        ret['purchasedpropertyname'] = txJson['purchasedpropertyname']
        ret['purchasedtokens'] = txJson['purchasedtokens']
        ret['issuertokens'] = txJson['issuertokens']

    return json.dumps([ ret ] , sort_keys=True, indent=4) #only send back mapped schema
