#  Copyright (C) 2023 Yesh
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Affero General Public License as
#  published by the Free Software Foundation, either version 3 of the
#  License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""各种 NexusPHP 站点的客户端。"""

import byre.clients.byr as byr
import byre.clients.tju as tju

APIS = [
    byr.ByrApi,
    tju.TjuPtApi,
]

SITES = dict((api.site(), api) for api in APIS)

CLIENTS = dict((api.site(), client) for client, api in zip([byr.ByrClient, tju.TjuPtClient], APIS))
