#!/usr/bin/env python

from utc_bot import UTCBot, start_bot
import proto.utc_bot as pb
import betterproto
import math
from time import time
import re

import asyncio
import random

import json

from typing import Optional

"""Constant listed from case packet"""
DAYS_IN_YEAR = 252
LAST_RATE_ROR_USD = 0.25
LAST_RATE_HAP_USD = 0.5
LAST_RATE_HAP_ROR = 2
TODAY = 0
YEAR = 0


TICK_SIZES = {'6RH': 0.00001, '6RM': 0.00001, '6RU': 0.00001, '6RZ': 0.00001, '6HH': 0.00002, \
    '6HM': 0.00002, '6HU': 0.00002, '6HZ': 0.00002, 'RHH': 0.0001, 'RHM': 0.0001, 'RHU': 0.0001, 'RHZ': 0.0001, "RORUSD": 0.00001}
LOT_SIZES = {'6RH': 100000, '6RM': 100000, '6RU': 100000, '6RZ': 100000, '6HH': 100000, \
    '6HM': 100000, '6HU': 100000, '6HZ': 100000, 'RHH': 50000, 'RHM': 50000, 'RHU': 50000, 'RHZ': 50000, "RORUSD": 100000}
FUTURES = [i+j for i in ["6R", "6H", "RH"] for j in ["H", "M", "U", "Z"]]
FUTURES_EXPIRY = {"H": 63, "M": 126, "U": 189, "Z": 252}




'''Rounds price to nearest tick_number above'''
def round_nearest(x, tick=0.0001):
    return round(round(x / tick) * tick, -int(math.floor(math.log10(tick))))

'''Finds daily interest rates from annual rate'''
def daily_rate(daily_rate):
    return math.pow(daily_rate, 1/252)

''' Returns 0 if not int, or else return int rep of string'''
def IsInt(s):
    try: 
        return int(s)
    except ValueError:
        return 0

''' Returns base and quote for a given asset as string '''
def parseAssetName(asset):
    if(asset[0] == '6'):
        quote = 'USD'
        if(asset[1] == 'R'):
            base = 'ROR'
        else:
            base = 'HAP'
    else:
        base = 'HAP'
        quote = 'ROR'
    return base, quote

class PositionTrackerBot(UTCBot):
    """
    An example bot that tracks its position, implements linear fading,
    and prints out PnL information as 
    computed by itself vs what was computed by the exchange
    """
    async def place_bids(self, asset):
        """
        Places and modifies a single bid, storing it by asset
        based upon the basic market making functionality
        """
        if FUTURES_EXPIRY[asset[2]] < TODAY:
            return []
        orders = await self.basic_mm(asset, self.fair[asset], self.edges[asset],
            self.size[asset], self.params["limit"],self.max_widths[asset])
        reqs = []
        for index, price in enumerate(orders['bid_prices']):
            if orders['bid_sizes'][index] != 0:
                reqs.append(self.modify_order(
                    self.bidorderid[asset][index],
                    asset,
                    pb.OrderSpecType.LIMIT,
                    pb.OrderSpecSide.BID,
                    orders['bid_sizes'][index],
                    round_nearest(price, TICK_SIZES[asset]),
                ))
                # self.bidorderid[asset][index] = resp.order_id
        return reqs

    async def place_asks(self, asset):
        """
        Places and modifies a single bid, storing it by asset
        based upon the basic market making functionality
        """
        reqs = []
        if FUTURES_EXPIRY[asset[2]] < TODAY:
            return []
        orders = await self.basic_mm(asset, self.fair[asset], self.edges[asset],
            self.size[asset], self.params["limit"],self.max_widths[asset])
        for index, price in enumerate(orders['ask_prices']):
            if orders['ask_sizes'][index] != 0:
                reqs.append(self.modify_order(
                    self.askorderid[asset][index],
                    asset,
                    pb.OrderSpecType.LIMIT,
                    pb.OrderSpecSide.ASK,
                    orders['ask_sizes'][index],
                    round_nearest(price, TICK_SIZES[asset]),
                ))
                # self.askorderid[asset][index] = resp.order_id
        return reqs
    async def evaluate_fairs(self):
        ##TO Do
        """
        Modify your long term fair values based on market updates, statistical calculations, 
        etc. 

        Calculate based off of
        1) interest parity
        2) mid price
        3) 
        """

        for asset in FUTURES:
            expiry = FUTURES_EXPIRY[asset[2]]
            if expiry > TODAY: # Check if expired
                self.fair[asset] = self.mid[asset]
                spot = self.mid[asset]
                base, quote = parseAssetName(asset)
                if(base == 'ROR'):
                    last = LAST_RATE_ROR_USD
                elif(quote == 'USD'):
                    last = LAST_RATE_HAP_USD
                else:
                    last = LAST_RATE_HAP_ROR
                if spot == None:
                    fair = last
                else:
                    ir_base = math.pow(self.interestRates[base],expiry-TODAY)
                    ir_quote = math.pow(self.interestRates[quote],expiry-TODAY)
                    # print(asset + ": Base IR=" + str(ir_base) + ", Quote IR=" + str(ir_quote))
                    t = (DAYS_IN_YEAR-TODAY)/DAYS_IN_YEAR
                    # spot = last*t+spot*(1-t)
                    forwardInterestParity = round_nearest(spot * float(ir_base) / float(ir_quote), TICK_SIZES[asset])
                    fair = forwardInterestParity
                    # fair = '''forwardInterestParity*(0.6)*(1-t) + self.mid[asset]*0.2 + '''t*0.2*last
                    # print("SPOT: " + str(spot) + ", FAIR: " + str(fair))
            else: # use mid price if expired
                fair = self.mid[asset]
            self.fair[asset] = fair # Updates the fair price across the bot
        spot = self.mid['RORUSD']
        if spot == None:
            self.fair['RORUSD'] = LAST_RATE_ROR_USD
        else: 
            ir_base = math.pow(self.interestRates['ROR'],expiry-TODAY)
            ir_quote = math.pow(self.interestRates['USD'],expiry-TODAY)
            self.fair['RORUSD'] = round_nearest(float(spot) * float(ir_base) / float(ir_quote), TICK_SIZES['RORUSD'])
    
    async def spot_market(self):
        """
        Interaction within the spot market primarily consists
        of zeroing out the exposure to RORUSD exchange rates
        as best as possible, using market orders (assume spot
        market already is quite liquid)
        """
        net_position = self.pos["RORUSD"]
        for month in ["H", "M", "U", "Z"]:
            net_position += 0.05 * self.pos['RH' + month]
        net_position = round(net_position)
        bids_left = self.params["spot_limit"] - self.pos["RORUSD"]
        asks_left = self.params["spot_limit"] + self.pos["RORUSD"]
        if bids_left <= 0:
            resp = await self.place_order(
                "RORUSD",
                pb.OrderSpecType.MARKET,
                pb.OrderSpecSide.ASK,
                abs(bids_left) + 1,
            )
        elif asks_left <= 0: 
            resp = await self.place_order(
                "RORUSD",
                pb.OrderSpecType.MARKET,
                pb.OrderSpecSide.BID,
                abs(asks_left) + 1,
            )
        elif (net_position > 0):
            resp = await self.place_order(
                "RORUSD",
                pb.OrderSpecType.MARKET,
                pb.OrderSpecSide.ASK,
                min(abs(net_position), asks_left) + 1,
            )
        elif (net_position < 0):
            resp = await self.place_order(
                "RORUSD",
                pb.OrderSpecType.MARKET,
                pb.OrderSpecSide.ASK,
                min(abs(net_position), bids_left) + 1,
            )


    async def basic_mm(self, asset, fair, width, clip, max_pos, max_range):
        """
        Asset - Asset name on exchange
        Fair - Your prediction of the asset's true value
        Width - Your spread when quoting, i.e. difference between bid price and ask price
        Clip - Your maximum quote size on each level
        Max_Pos - The maximum number of contracts you are willing to hold (we just use risk limit here)
        Max_Range - The greatest you are willing to adjust your fair value by
        """

        ##The rate at which you fade is optimized so that you reach your max position
        ##at the same time you reach maximum range on the adjusted fair
        fade = (max_range / 2.0) / max_pos
        adjusted_fair = fair - self.pos[asset] * fade


        ##Best bid, best ask prices
        bid_p = adjusted_fair - width / 2.0
        ask_p = adjusted_fair + width / 2.0

        ##Next best bid, ask price
        bid_p2 = min(adjusted_fair - clip * fade - width / 2.0, 
            bid_p - TICK_SIZES[asset])
        ask_p2 = min(adjusted_fair + clip * fade + width / 2.0, 
            ask_p + TICK_SIZES[asset])
        # print('BID/ASK for ',asset, ": ", bid_p, ask_p)
        
        ##Remaining ability to quote
        bids_left = max_pos - self.pos[asset]
        asks_left = max_pos + self.pos[asset]
        # print("For asset " + asset + ", you have " + str(bids_left) + "bids left, and " + str(asks_left) + "asks left.")
        if bids_left <= 0:
            #reduce your position as you are violating risk limits!
            ask_p = bid_p
            ask_s = clip
            ask_p2 = bid_p + TICK_SIZES[asset]
            ask_s2 = clip
            bid_s = 0
            bid_s2 = 0
        elif asks_left <= 0:
            #reduce your position as you are violating risk limits!
            bid_p = ask_p
            bid_s = clip
            bid_p2 = ask_p - TICK_SIZES[asset]
            bid_s2 = clip
            ask_s = 0
            ask_s2 = 0
        else:
            #bid and ask size setting
            bid_s = min(bids_left, clip)
            bid_s2 = max(0, min(bids_left - clip, clip))
            ask_s = min(asks_left, clip)
            ask_s2 = max(0, min(asks_left - clip, clip))

        return {'asset': asset,
                'bid_prices': [bid_p, bid_p2], 
                'bid_sizes': [bid_s, bid_s2],
                'ask_prices': [ask_p, ask_p2],
                'ask_sizes': [ask_s, ask_s2],
                'adjusted_fair': adjusted_fair,
                'fade': fade}

    async def handle_round_started(self):
        """
        Important variables below, some can be more dynamic to improve your case.
        Others are important to tracking pnl - cash, pos, 
        Bidorderid, askorderid track order information so we can modify existing
        orders using the basic MM information (Right now only place 2 bids/2 asks max)
        """
        self.cash = 0.0
        self.pos = {asset:0 for asset in FUTURES + ["RORUSD"]}
        self.fair = {asset:5 for asset in FUTURES + ["RORUSD"]}
        self.mid = {asset: None for asset in FUTURES + ["RORUSD"]}
        self.max_widths = {asset:0.1 for asset in FUTURES}
        
        self.bidorderid = {asset:["",""] for asset in FUTURES}
        self.askorderid = {asset:["",""] for asset in FUTURES}

        self.interestRates = {asset:1 for asset in ['ROR', 'HAP', 'USD']}
        
        self.edges = {asset:TICK_SIZES[asset]*5 for asset in FUTURES}
        self.edges["RORUSD"] = TICK_SIZES["RORUSD"]*2

        self.size = {asset:5 for asset in FUTURES}
        self.size["RORUSD"] = 1
        """
        Constant params with respect to assets. Modify this is you would like to change
        parameters based on asset
        """
        self.params = {
            "limit": 100,
            "spot_limit": 8
        }
    async def handle_exchange_update(self, update: pb.FeedMessage):
        kind, _ = betterproto.which_one_of(update, "msg")

        #Possible exchange updates: 'market_snapshot_msg','fill_msg'
        #'liquidation_msg','generic_msg', 'trade_msg', 'pnl_msg', etc.
        """
        Calculate PnL based upon market to market contracts and tracked cash 
        """
        if kind == "pnl_msg":
            my_m2m = self.cash
            for asset in ([i+j for i in ["6R", "6H"] for j in ["H", "M", "U", "Z"]] + ["RORUSD"]):
                my_m2m += self.mid[asset] * self.pos[asset] if self.mid[asset] is not None else 0
            for asset in (["RH" + j for j in ["H", "M", "U", "Z"]]):
                my_m2m += (self.mid[asset] * self.pos[asset] * self.mid["RORUSD"] 
                    if (self.mid[asset] is not None and self.mid["RORUSD"] is not None) else 0)
            print("M2M", update.pnl_msg.realized_pnl, update.pnl_msg.m2m_pnl, my_m2m)
        #Update position upon fill messages of your trades
        elif kind == "fill_msg":
            if update.fill_msg.order_side == pb.FillMessageSide.BUY:
                self.cash -= update.fill_msg.filled_qty * float(update.fill_msg.price)
                self.pos[update.fill_msg.asset] += update.fill_msg.filled_qty
                if update.fill_msg.asset != 'RORUSD':
                    reqs = await self.place_bids(update.fill_msg.asset)
                    resps = await asyncio.gather(*reqs)
                    for i, resp in enumerate(resps):
                        self.bidorderid[update.fill_msg.asset][i] = resp.order_id
            else:
                self.cash += update.fill_msg.filled_qty * float(update.fill_msg.price)
                self.pos[update.fill_msg.asset] -= update.fill_msg.filled_qty
                if update.fill_msg.asset != 'RORUSD':
                    reqs = await self.place_asks(update.fill_msg.asset)
                    resps = await asyncio.gather(*reqs)
                    for i, resp in enumerate(resps):
                        self.askorderid[update.fill_msg.asset][i] = resp.order_id
            await self.spot_market()
        #Identify mid price through order book updates
        elif kind == "market_snapshot_msg":
            for asset in (FUTURES + ["RORUSD"]):
                book = update.market_snapshot_msg.books[asset]

                mid: "Optional[float]"
                if len(book.asks) > 0:
                    if len(book.bids) > 0:
                        mid = (float(book.asks[0].px) + float(book.bids[0].px)) / 2
                    else:
                        mid = float(book.asks[0].px)
                elif len(book.bids) > 0:
                    mid = float(book.bids[0].px)
                else:
                    mid = None

                self.mid[asset] = mid
        #Competition event messages
        elif kind == "generic_msg":
            data = update.generic_msg.message.split(',')
            if(0 < IsInt(data[0])):
                TODAY = data[0]
                self.interestRates['ROR'] = daily_rate(float(data[1]))
                self.interestRates['HAP'] = daily_rate(float(data[2]))
                self.interestRates['USD'] = daily_rate(float(data[3]))
                print(update.generic_msg.message)
                # print(self.interestRates['ROR'], self.interestRates['HAP'], self.interestRates['USD'])
                await self.evaluate_fairs()
                bid_reqs = []
                ask_reqs = []
                for asset in FUTURES:
                    bid_reqs += await self.place_bids(asset)
                    ask_reqs += await self.place_asks(asset)
                bid_resps = await asyncio.gather(*bid_reqs)
                ask_resps = await asyncio.gather(*ask_reqs)
                for idx, resp in enumerate(bid_resps):
                    asset = FUTURES[math.floor(idx/2)]
                    self.bidorderid[asset][idx%2] = resp.order_id
                for idx, resp in enumerate(ask_resps):
                    asset = FUTURES[math.floor(idx/2)]
                    self.askorderid[asset][idx%2] = resp.order_id
                await self.spot_market()
            elif("New Federal Funds Target" in data[0]):
                d = data.split(" ")
                currency = d[0]
                target = d[0]
                print("New Federal Funds Target for " + currency + ":" + target)
            else:
                pass
                print(update.generic_msg.message)
if __name__ == "__main__":
    start_bot(PositionTrackerBot)